"""Expose homework availability to every template (for the nav link/badge)."""

from courses.models import BatchEnrollment

from .models import HomeTask, HomeworkSubmission


def homework_badges(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and getattr(user, "role", None) == "student"):
        return {}

    plan_by_batch = {
        e.batch_id: e.plan
        for e in BatchEnrollment.objects.filter(student=user, is_active=True).select_related("plan")
    }
    if not plan_by_batch:
        return {"hw_has": False, "hw_pending": 0}

    tasks = (
        HomeTask.objects.filter(live_class__batch_id__in=plan_by_batch.keys())
        .select_related("live_class")
        .prefetch_related("allowed_plans")
    )
    visible = [t for t in tasks if t.is_open_to(plan_by_batch.get(t.live_class.batch_id))]
    submitted = set(
        HomeworkSubmission.objects.filter(
            student=user, hometask__in=visible
        ).values_list("hometask_id", flat=True)
    )
    pending = sum(1 for t in visible if t.id not in submitted)
    return {"hw_has": bool(visible), "hw_pending": pending}