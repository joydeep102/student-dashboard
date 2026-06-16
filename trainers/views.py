from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from classroom.models import LiveClass
from courses.models import Batch, BatchScheduleSlot

from .forms import VideoSubmissionForm
from .models import VideoSubmission


def trainer_required(view):
    """Allow only instructors (and admins) into the trainer portal."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = getattr(request.user, "role", None)
        if role not in ("instructor", "admin") and not request.user.is_superuser:
            raise PermissionDenied("Trainer access only.")
        return view(request, *args, **kwargs)

    return wrapper


@trainer_required
def dashboard(request):
    submissions = (
        VideoSubmission.objects.filter(trainer=request.user)
        .select_related("batch", "required_plan")
        .order_by("-created_at")
    )
    counts = {
        "pending": submissions.filter(status=VideoSubmission.Status.PENDING).count(),
        "approved": submissions.filter(status=VideoSubmission.Status.APPROVED).count(),
        "rejected": submissions.filter(status=VideoSubmission.Status.REJECTED).count(),
    }
    return render(
        request,
        "trainers/dashboard.html",
        {"submissions": submissions, "counts": counts},
    )


@trainer_required
def upload(request):
    if request.method == "POST":
        form = VideoSubmissionForm(request.POST, request.FILES, trainer=request.user)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.trainer = request.user
            sub.save()
            messages.success(
                request,
                "Video submitted! It's now pending admin approval. "
                "Once approved it will be uploaded to YouTube and published to the batch.",
            )
            return redirect("trainers:dashboard")
    else:
        form = VideoSubmissionForm(trainer=request.user)
    return render(request, "trainers/upload.html", {"form": form})


def _can_teach(user, batch):
    """A trainer may conduct a batch whose course they instruct (admins: any)."""
    return (
        user.is_superuser
        or getattr(user, "role", None) == "admin"
        or batch.course.instructor_id == user.id
    )


@trainer_required
def live(request):
    """Trainer's live-class console: weekly schedule + start today's class."""
    batches = (
        Batch.objects.filter(is_active=True, course__instructor=request.user)
        .prefetch_related("schedule_slots", "schedule_slots__required_plan")
        .select_related("course")
    )
    today = timezone.localdate()
    today_wd = today.weekday()

    # Classes already running/scheduled today for these batches.
    live_today = (
        LiveClass.objects.filter(batch__in=batches, start_time__date=today)
        .exclude(status=LiveClass.Status.CANCELLED)
        .select_related("batch")
    )
    live_by_batch = {}
    for lc in live_today:
        if lc.live_state in ("live", "upcoming"):
            live_by_batch.setdefault(lc.batch_id, []).append(lc)

    rows = []
    for b in batches:
        slots = list(b.schedule_slots.all())
        rows.append(
            {
                "batch": b,
                "slots": slots,
                "today_slots": [s for s in slots if s.weekday == today_wd],
                "live": live_by_batch.get(b.id, []),
            }
        )

    return render(
        request,
        "trainers/live.html",
        {"rows": rows, "today_name": today.strftime("%A"), "has_batches": bool(rows)},
    )


@trainer_required
def start_live(request, slot_id):
    """Start (or rejoin) a live class for a scheduled slot — only on its weekday."""
    if request.method != "POST":
        return redirect("trainers:live")
    slot = get_object_or_404(BatchScheduleSlot.objects.select_related("batch", "batch__course"), pk=slot_id)
    if not _can_teach(request.user, slot.batch):
        raise PermissionDenied("You don't conduct this batch.")

    today = timezone.localdate()
    if slot.weekday != today.weekday():
        messages.error(
            request,
            f"This class is scheduled for {slot.get_weekday_display()}, not today "
            f"({today.strftime('%A')}). You can only start it on its scheduled day.",
        )
        return redirect("trainers:live")

    # Re-use a class this console already started today (avoid duplicates on a
    # double click), but don't hijack a separately pre-scheduled class.
    existing = (
        LiveClass.objects.filter(
            batch=slot.batch, start_time__date=today, status=LiveClass.Status.LIVE
        )
        .order_by("-start_time")
        .first()
    )
    lc = existing
    if lc is None:
        lc = LiveClass.objects.create(
            batch=slot.batch,
            title=f"{slot.batch.name} · {slot.get_weekday_display()} live class",
            start_time=timezone.now(),
            duration_minutes=slot.duration_minutes,
            required_plan=slot.required_plan,
            status=LiveClass.Status.LIVE,
            meet_link=request.POST.get("meet_link", "").strip(),
        )
        lc.refresh_from_db()  # the post_save signal may have filled meet_link

    if lc.meet_link:
        return redirect(lc.meet_link)
    messages.warning(
        request,
        "Class started, but no Google Meet link was generated (Google not connected). "
        "Add a meeting link to this class so students can join.",
    )
    return redirect("trainers:live")


@trainer_required
def end_live(request, pk):
    if request.method != "POST":
        return redirect("trainers:live")
    lc = get_object_or_404(LiveClass.objects.select_related("batch", "batch__course"), pk=pk)
    if not _can_teach(request.user, lc.batch):
        raise PermissionDenied("You don't conduct this batch.")
    lc.status = LiveClass.Status.ENDED
    lc.save(update_fields=["status"])
    messages.success(request, "Live class ended.")
    return redirect("trainers:live")
