"""Instructor Course Studio — build & manage Udemy-style recorded courses.

Instructors create their own courses, add sections and lectures (unlisted
YouTube ids), set the price and thumbnail, and publish — all from the front end.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import Lecture, RecordedCourse, Section

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
    """List the instructor's recorded courses."""
    courses = (
        RecordedCourse.objects.filter(instructor=request.user)
        .order_by("-updated_at")
    )
    return render(request, "trainers/courses.html", {"courses": courses})


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
