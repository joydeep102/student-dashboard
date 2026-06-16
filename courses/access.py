"""Batch + plan-tier access rules, shared by views.

A student can open a piece of content (live class or video lesson) only when:
  1. they have an active enrollment in that content's batch, AND
  2. their plan's level is >= the content's required plan level
     (content with no required plan is open to everyone in the batch).
"""

from .models import BatchEnrollment


def get_enrollment(user, batch):
    """Return the student's active enrollment in ``batch`` (or None)."""
    if not user.is_authenticated:
        return None
    return (
        BatchEnrollment.objects.filter(student=user, batch=batch, is_active=True)
        .select_related("plan")
        .first()
    )


def can_access(enrollment, content):
    """True if ``enrollment`` grants access to ``content`` (lesson/live class).

    Live classes gate on an explicit set of allowed plans (``is_open_to``);
    lessons still gate on the minimum plan level.
    """
    if enrollment is None:
        return False
    checker = getattr(content, "is_open_to", None)
    if checker is not None:
        return checker(enrollment.plan)
    required = getattr(content, "required_level", 0)
    return enrollment.plan.level >= required
