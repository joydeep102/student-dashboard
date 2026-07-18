"""Instructor Course Studio — build & manage Udemy-style recorded courses.

Instructors create their own courses, add sections and lectures (unlisted
YouTube ids), set the price and thumbnail, and publish — all from the front end.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import CoursePayment, Lecture, Payout, RecordedCourse, Section
from courses.payment_config import instructor_earnings

from .views import trainer_required


def _own_course(request, slug):
    """Fetch a course the current user is allowed to edit (owner or admin)."""
    course = get_object_or_404(RecordedCourse, slug=slug)
    is_admin = request.user.is_superuser or getattr(request.user, "role", None) == "admin"
    if not is_admin and course.instructor_id != request.user.id:
        raise PermissionDenied("This isn't your course.")
    return course


def _next_order(qs):
    return (qs.aggregate(m=Max("order"))["m"] or 0) + 1


@trainer_required
def my_courses(request):
    """List the instructor's courses with sales & earnings."""
    paid = Q(payments__status=CoursePayment.Status.PAID)
    pending = Q(payments__status=CoursePayment.Status.PENDING)
    courses = list(
        RecordedCourse.objects.filter(instructor=request.user)
        .annotate(
            sales=Count("payments", filter=paid, distinct=True),
            revenue=Sum("payments__amount", filter=paid),
            students=Count("enrollments", filter=Q(enrollments__is_active=True), distinct=True),
            pending=Count("payments", filter=pending, distinct=True),
        )
        .order_by("-updated_at")
    )
    totals = {
        "revenue": sum(c.revenue or 0 for c in courses),
        "sales": sum(c.sales for c in courses),
        "students": sum(c.students for c in courses),
        "pending": sum(c.pending for c in courses),
    }
    return render(
        request,
        "trainers/courses.html",
        {
            "courses": courses,
            "totals": totals,
            "earnings": instructor_earnings(request.user),
        },
    )


@trainer_required
@require_POST
def request_payout(request):
    """Instructor requests a payout of (part of) their available balance."""
    earn = instructor_earnings(request.user)
    available = float(earn["available"])
    try:
        amount = round(float(request.POST.get("amount") or available), 2)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0 or amount > available + 0.01:
        messages.error(
            request,
            "You can request up to ₹{:,.0f}.".format(available) if available > 0
            else "You have no balance available to request right now.",
        )
        return redirect("trainers:courses")
    Payout.objects.create(
        instructor=request.user,
        amount=amount,
        status=Payout.Status.REQUESTED,
        note=(request.POST.get("note") or "").strip(),
        created_by=request.user,
    )
    messages.success(request, f"Payout request for ₹{amount:,.0f} submitted for approval.")
    return redirect("trainers:courses")


@staff_member_required
def payouts(request):
    """Admin view: pending payout requests + every instructor's balance."""
    User = get_user_model()
    pending = (
        Payout.objects.filter(status=Payout.Status.REQUESTED)
        .select_related("instructor")
        .order_by("created_at")
    )
    instructors = (
        User.objects.filter(role__in=["instructor", "admin"])
        .filter(recorded_courses__isnull=False)
        .distinct()
        .order_by("first_name", "email")
    )
    rows = [{"instructor": u, "earn": instructor_earnings(u)} for u in instructors]
    rows = [r for r in rows if r["earn"]["gross"] or r["earn"]["paid_out"]]
    return render(request, "trainers/payouts.html", {"rows": rows, "pending": pending})


@staff_member_required
@require_POST
def payout_approve(request, pk):
    """Approve a payout request — marks it paid (money sent outside the app)."""
    payout = get_object_or_404(Payout, pk=pk, status=Payout.Status.REQUESTED)
    payout.note = (request.POST.get("note") or payout.note).strip()
    payout.created_by = payout.created_by or request.user
    payout.mark_paid()
    messages.success(
        request, f"Approved ₹{payout.amount:,.0f} payout to {payout.instructor.display_name}."
    )
    return redirect("trainers:payouts")


@staff_member_required
@require_POST
def payout_reject(request, pk):
    payout = get_object_or_404(Payout, pk=pk, status=Payout.Status.REQUESTED)
    payout.status = Payout.Status.REJECTED
    payout.save(update_fields=["status"])
    messages.success(request, "Payout request rejected.")
    return redirect("trainers:payouts")


@staff_member_required
@require_POST
def payout_pay(request, user_id):
    """Admin records a payout to an instructor directly (already transferred)."""
    User = get_user_model()
    instructor = get_object_or_404(User, pk=user_id, role__in=["instructor", "admin"])
    earn = instructor_earnings(instructor)
    try:
        amount = round(float(request.POST.get("amount") or earn["balance"]), 2)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        messages.error(request, "Enter a payout amount greater than zero.")
        return redirect("trainers:payouts")
    payout = Payout.objects.create(
        instructor=instructor,
        amount=amount,
        status=Payout.Status.PAID,
        note=(request.POST.get("note") or "").strip(),
        created_by=request.user,
    )
    payout.mark_paid()
    messages.success(request, f"Recorded ₹{amount:,.0f} payout to {instructor.display_name}.")
    return redirect("trainers:payouts")


@trainer_required
def course_sales(request, slug):
    """A course's buyers list (sales) for its instructor."""
    course = _own_course(request, slug)
    payments = (
        course.payments.select_related("student")
        .exclude(status=CoursePayment.Status.CREATED)
        .order_by("-created_at")
    )
    paid = [p for p in payments if p.status == CoursePayment.Status.PAID]
    stats = {
        "revenue": sum(p.amount for p in paid),
        "sales": len(paid),
        "pending": sum(1 for p in payments if p.status == CoursePayment.Status.PENDING),
    }
    return render(
        request,
        "trainers/course_sales.html",
        {"course": course, "payments": payments, "stats": stats},
    )


@trainer_required
@require_POST
def course_create(request):
    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "Please enter a course title.")
        return redirect("trainers:courses")
    course = RecordedCourse.objects.create(title=title, instructor=request.user)
    messages.success(request, "Course created — add your curriculum below.")
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
def course_edit(request, slug):
    """The course builder: details form + curriculum (sections & lectures)."""
    course = _own_course(request, slug)

    if request.method == "POST":
        course.title = (request.POST.get("title") or course.title).strip()
        course.subtitle = (request.POST.get("subtitle") or "").strip()
        course.description = (request.POST.get("description") or "").strip()
        try:
            course.price = max(0, int(float(request.POST.get("price") or 0)))
        except (TypeError, ValueError):
            pass
        if request.FILES.get("thumbnail"):
            course.thumbnail = request.FILES["thumbnail"]
        course.save()
        messages.success(request, "Course details saved.")
        return redirect("trainers:course_edit", slug=course.slug)

    sections = course.sections.prefetch_related("lectures").all()
    return render(
        request,
        "trainers/course_edit.html",
        {"course": course, "sections": sections},
    )


@trainer_required
@require_POST
def course_publish(request, slug):
    course = _own_course(request, slug)
    if not course.sections.filter(lectures__isnull=False).exists():
        messages.error(request, "Add at least one lecture before publishing.")
        return redirect("trainers:course_edit", slug=course.slug)
    course.is_published = not course.is_published
    course.save(update_fields=["is_published", "updated_at"])
    messages.success(
        request,
        "Course published — it's now live in the catalog." if course.is_published
        else "Course unpublished — hidden from the catalog.",
    )
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
@require_POST
def course_delete(request, slug):
    course = _own_course(request, slug)
    course.delete()
    messages.success(request, "Course deleted.")
    return redirect("trainers:courses")


# --- Sections --------------------------------------------------------------
@trainer_required
@require_POST
def section_add(request, slug):
    course = _own_course(request, slug)
    title = (request.POST.get("title") or "").strip()
    if title:
        Section.objects.create(
            course=course, title=title, order=_next_order(course.sections)
        )
        messages.success(request, "Section added.")
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
@require_POST
def section_edit(request, slug, sid):
    course = _own_course(request, slug)
    section = get_object_or_404(Section, pk=sid, course=course)
    title = (request.POST.get("title") or "").strip()
    if title:
        section.title = title
        section.save(update_fields=["title"])
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
@require_POST
def section_delete(request, slug, sid):
    course = _own_course(request, slug)
    get_object_or_404(Section, pk=sid, course=course).delete()
    messages.success(request, "Section deleted.")
    return redirect("trainers:course_edit", slug=course.slug)


# --- Lectures --------------------------------------------------------------
def _apply_lecture_fields(lecture, post):
    lecture.title = (post.get("title") or lecture.title).strip()
    lecture.youtube_id = (post.get("youtube_id") or "").strip()
    lecture.is_preview = post.get("is_preview") == "on"
    lecture.qa_enabled = post.get("qa_enabled") == "on"
    lecture.description = (post.get("description") or "").strip()
    try:
        minutes = float(post.get("duration_min") or 0)
        lecture.duration_seconds = max(0, int(minutes * 60))
    except (TypeError, ValueError):
        pass


@trainer_required
@require_POST
def lecture_add(request, slug, sid):
    course = _own_course(request, slug)
    section = get_object_or_404(Section, pk=sid, course=course)
    title = (request.POST.get("title") or "").strip()
    youtube_id = (request.POST.get("youtube_id") or "").strip()
    if not title or not youtube_id:
        messages.error(request, "A lecture needs a title and a YouTube video id.")
        return redirect("trainers:course_edit", slug=course.slug)
    lecture = Lecture(section=section, order=_next_order(section.lectures))
    _apply_lecture_fields(lecture, request.POST)
    lecture.save()
    messages.success(request, "Lecture added.")
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
@require_POST
def lecture_edit(request, slug, lid):
    course = _own_course(request, slug)
    lecture = get_object_or_404(Lecture, pk=lid, section__course=course)
    _apply_lecture_fields(lecture, request.POST)
    lecture.save()
    messages.success(request, "Lecture updated.")
    return redirect("trainers:course_edit", slug=course.slug)


@trainer_required
@require_POST
def lecture_delete(request, slug, lid):
    course = _own_course(request, slug)
    get_object_or_404(Lecture, pk=lid, section__course=course).delete()
    messages.success(request, "Lecture deleted.")
    return redirect("trainers:course_edit", slug=course.slug)
