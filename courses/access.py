"""Batch + plan-tier access rules, shared by views.

A student can open a piece of content (live class or video lesson) only when:
  1. they have an active enrollment in that content's batch, AND
  2. their plan's level is >= the content's required plan level
     (content with no required plan is open to everyone in the batch).

One extra rule for recorded courses: a **provisional** enrollment (a manual-UPI
payment still awaiting admin verification) can preview only the first
``PROVISIONAL_PREVIEW_LESSONS`` plan-accessible lessons. Once the admin approves
the payment the enrollment becomes full and the whole plan unlocks.
"""

from .models import BatchEnrollment, CourseEnrollment, Lesson


def preview_count():
    from .payment_config import payment_config

    return payment_config().preview_lessons


def get_enrollment(user, batch):
    """Return the student's active enrollment in ``batch`` (or None)."""
    if not user.is_authenticated:
        return None
    return (
        BatchEnrollment.objects.filter(student=user, batch=batch, is_active=True)
        .select_related("plan")
        .first()
    )


def unlocked_lesson_ids(enrollment, lessons):
    """Ids among ``lessons`` (ordered) the enrollment may watch.

    Applies the plan-level gate and, for provisional enrollments, caps access to
    the first ``preview_count()`` plan-accessible lessons.
    """
    if enrollment is None:
        return set()
    preview_left = preview_count() if enrollment.is_provisional else None
    ids = set()
    for lesson in lessons:
        if enrollment.plan.level < lesson.required_level:
            continue
        if preview_left is not None:
            if preview_left <= 0:
                continue
            preview_left -= 1
        ids.add(lesson.id)
    return ids


def can_access(enrollment, content):
    """True if ``enrollment`` grants access to ``content`` (lesson/live class).

    Live classes gate on an explicit set of allowed plans (``is_open_to``).
    Lessons gate on the minimum plan level, plus the provisional preview cap.
    """
    if enrollment is None:
        return False

    if not isinstance(content, Lesson):
        checker = getattr(content, "is_open_to", None)
        if checker is not None:
            return checker(enrollment.plan)
        return enrollment.plan.level >= getattr(content, "required_level", 0)

    # Lesson: reuse the list logic against the whole (ordered) batch so the
    # provisional preview count is computed consistently everywhere.
    lessons = list(content.batch.lessons.all())
    return content.id in unlocked_lesson_ids(enrollment, lessons)


# ---------------------------------------------------------------------------
# Recorded-course (Udemy-style) lecture access
# ---------------------------------------------------------------------------
def get_course_enrollment(user, course):
    """Return the student's active enrollment in ``course`` (or None)."""
    if not user.is_authenticated:
        return None
    return CourseEnrollment.objects.filter(
        student=user, course=course, is_active=True
    ).first()


def unlocked_lecture_ids(enrollment, ordered_lectures):
    """Ids among ``ordered_lectures`` (curriculum order) the viewer may watch.

    * Preview lectures are always watchable (free samples, even logged-out).
    * A full enrollment unlocks everything.
    * A provisional enrollment (manual-UPI awaiting verification) unlocks only
      the first ``preview_count()`` lectures.
    """
    ids = {lec.id for lec in ordered_lectures if lec.is_preview}
    if enrollment is None or not enrollment.is_active:
        return ids
    if not enrollment.is_provisional:
        ids.update(lec.id for lec in ordered_lectures)
        return ids
    for lec in ordered_lectures[: preview_count()]:
        ids.add(lec.id)
    return ids


def can_watch_lecture(user, lecture, enrollment):
    """True if the viewer may watch ``lecture`` right now."""
    if lecture.is_preview:
        return True
    ordered = lecture.section.course.ordered_lectures()
    return lecture.id in unlocked_lecture_ids(enrollment, ordered)
