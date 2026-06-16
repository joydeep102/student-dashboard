from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from courses.access import can_access, get_enrollment

from .models import LiveClass


@login_required
def join_live(request, pk):
    """Send an enrolled, sufficiently-upgraded student into the Meet.

    Access requires an active enrollment in the class's batch AND a plan level
    that meets the class's required plan. Lower-plan students get a locked page.
    """
    live_class = get_object_or_404(LiveClass.objects.select_related("batch", "required_plan"), pk=pk)
    enrollment = get_enrollment(request.user, live_class.batch)

    if enrollment is None:
        return render(
            request, "courses/not_enrolled.html", {"batch": live_class.batch}, status=403
        )
    if not can_access(enrollment, live_class):
        return render(
            request,
            "courses/locked.html",
            {"batch": live_class.batch, "item": live_class, "kind": "live class"},
            status=403,
        )

    if live_class.meet_link and live_class.is_joinable:
        return redirect(live_class.meet_link)

    return render(request, "classroom/waiting_room.html", {"live_class": live_class})
