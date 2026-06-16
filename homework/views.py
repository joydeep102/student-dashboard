from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from classroom.models import LiveClass
from courses.access import get_enrollment
from courses.models import Batch, BatchEnrollment

from .forms import HomeTaskForm, SubmissionForm
from .models import HomeTask, HomeworkSubmission, SubmissionImage


# --- access helpers --------------------------------------------------------
def _is_trainer(user):
    return user.is_authenticated and (
        getattr(user, "role", None) in ("instructor", "admin") or user.is_superuser
    )


def trainer_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _is_trainer(request.user):
            raise PermissionDenied("Trainer access only.")
        return view(request, *args, **kwargs)

    return wrapper


def _can_manage(user, batch):
    return (
        user.is_superuser
        or getattr(user, "role", None) == "admin"
        or batch.instructor_id == user.id
        or batch.course.instructor_id == user.id
    )


def _my_batches(user):
    qs = Batch.objects.all()
    if user.is_superuser or getattr(user, "role", None) == "admin":
        return qs
    return qs.filter(Q(instructor=user) | Q(course__instructor=user))


# --- trainer ---------------------------------------------------------------
@trainer_required
def give(request, class_pk):
    """Assign homework attached to a live class (same plan gating as the class)."""
    lc = get_object_or_404(
        LiveClass.objects.select_related("batch", "batch__course").prefetch_related("allowed_plans"),
        pk=class_pk,
    )
    if not _can_manage(request.user, lc.batch):
        raise PermissionDenied("You don't conduct this batch.")
    if request.method == "POST":
        form = HomeTaskForm(request.POST)
        if form.is_valid():
            ht = form.save(commit=False)
            ht.live_class = lc
            ht.created_by = request.user
            ht.save()
            ht.allowed_plans.set(lc.allowed_plans.all())  # inherit the class's plans
            messages.success(request, "Homework assigned — the class's students can now submit.")
            return redirect("homework:trainer_list")
    else:
        form = HomeTaskForm(initial={"title": f"Homework · {lc.title}"})
    return render(request, "homework/give.html", {"form": form, "live_class": lc})


@trainer_required
def trainer_list(request):
    tasks = (
        HomeTask.objects.filter(live_class__batch__in=_my_batches(request.user))
        .select_related("live_class", "live_class__batch")
        .prefetch_related("allowed_plans", "submissions")
        .order_by("-created_at")
    )
    rows = [
        {
            "task": t,
            "count": t.submissions.count(),
            "pending": t.submissions.filter(overall=HomeworkSubmission.Verdict.PENDING).count(),
        }
        for t in tasks
    ]
    return render(request, "homework/trainer_list.html", {"rows": rows})


@trainer_required
def submissions(request, pk):
    ht = get_object_or_404(
        HomeTask.objects.select_related("live_class__batch__course"), pk=pk
    )
    if not _can_manage(request.user, ht.batch):
        raise PermissionDenied
    subs = ht.submissions.select_related("student").prefetch_related("images")
    return render(request, "homework/submissions.html", {"ht": ht, "subs": subs})


@trainer_required
def review(request, pk):
    sub = get_object_or_404(
        HomeworkSubmission.objects.select_related(
            "hometask__live_class__batch__course", "student"
        ).prefetch_related("images"),
        pk=pk,
    )
    if not _can_manage(request.user, sub.hometask.batch):
        raise PermissionDenied
    if request.method == "POST":
        for img in sub.images.all():
            v = request.POST.get(f"img_{img.id}")
            if v in dict(SubmissionImage.Verdict.choices):
                img.verdict = v
                img.note = request.POST.get(f"note_{img.id}", "").strip()[:200]
                img.save(update_fields=["verdict", "note"])
        overall = request.POST.get("overall")
        if overall in dict(HomeworkSubmission.Verdict.choices):
            sub.overall = overall
        sub.remarks = request.POST.get("remarks", "").strip()
        sub.reviewed_at = timezone.now()
        sub.save(update_fields=["overall", "remarks", "reviewed_at"])
        messages.success(request, "Feedback saved.")
        return redirect("homework:submissions", pk=sub.hometask_id)
    return render(request, "homework/review.html", {"sub": sub})


# --- student ---------------------------------------------------------------
@login_required
def student_list(request):
    enrolls = (
        BatchEnrollment.objects.filter(student=request.user, is_active=True)
        .select_related("batch", "plan")
    )
    plan_by_batch = {e.batch_id: e.plan for e in enrolls}
    tasks = (
        HomeTask.objects.filter(live_class__batch_id__in=plan_by_batch.keys())
        .select_related("live_class", "live_class__batch")
        .prefetch_related("allowed_plans")
        .order_by("-created_at")
    )
    my_subs = {s.hometask_id: s for s in HomeworkSubmission.objects.filter(student=request.user)}
    rows = [
        {"task": t, "sub": my_subs.get(t.id)}
        for t in tasks
        if t.is_open_to(plan_by_batch.get(t.live_class.batch_id))
    ]
    return render(request, "homework/student_list.html", {"rows": rows})


@login_required
def submit(request, pk):
    ht = get_object_or_404(
        HomeTask.objects.select_related("live_class__batch").prefetch_related("allowed_plans"),
        pk=pk,
    )
    enrollment = get_enrollment(request.user, ht.batch)
    if enrollment is None or not ht.is_open_to(enrollment.plan):
        raise PermissionDenied("This homework isn't available for your plan.")

    sub = (
        HomeworkSubmission.objects.filter(hometask=ht, student=request.user)
        .prefetch_related("images")
        .first()
    )
    if request.method == "POST":
        form = SubmissionForm(request.POST, instance=sub)
        if form.is_valid():
            s = form.save(commit=False)
            s.hometask = ht
            s.student = request.user
            s.overall = HomeworkSubmission.Verdict.PENDING  # (re)submission → re-review
            s.reviewed_at = None
            s.save()
            for f in request.FILES.getlist("images"):
                SubmissionImage.objects.create(submission=s, image=f)
            messages.success(request, "Homework submitted — your trainer will review it.")
            return redirect("homework:student_list")
    else:
        form = SubmissionForm(instance=sub)
    return render(request, "homework/submit.html", {"ht": ht, "form": form, "sub": sub})