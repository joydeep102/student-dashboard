import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from classroom.google_meet import ensure_meet_link
from classroom.models import LiveClass
from courses.models import Batch, BatchScheduleSlot, Plan

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
    """A trainer may conduct a batch they're assigned to (its own instructor or
    the course instructor). Admins may conduct any batch."""
    return (
        user.is_superuser
        or getattr(user, "role", None) == "admin"
        or batch.instructor_id == user.id
        or batch.course.instructor_id == user.id
    )


@trainer_required
def live(request):
    """Trainer's live-class console: weekly schedule + start today's class."""
    from django.db.models import Q

    batches = (
        Batch.objects.filter(is_active=True)
        .filter(Q(instructor=request.user) | Q(course__instructor=request.user))
        .prefetch_related("schedule_slots", "schedule_slots__required_plan")
        .select_related("course")
        .distinct()
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

    # Upcoming scheduled classes (future, any day) so the trainer can see what's
    # already booked and avoid double-scheduling.
    now = timezone.now()
    upcoming = (
        LiveClass.objects.filter(
            batch__in=batches, status=LiveClass.Status.SCHEDULED, start_time__gt=now
        )
        .select_related("batch")
        .order_by("start_time")
    )
    upcoming_by_batch = {}
    for lc in upcoming:
        upcoming_by_batch.setdefault(lc.batch_id, []).append(lc)

    rows = []
    for b in batches:
        slots = list(b.schedule_slots.all())
        rows.append(
            {
                "batch": b,
                "slots": slots,
                "today_slots": [s for s in slots if s.weekday == today_wd],
                "live": live_by_batch.get(b.id, []),
                "upcoming": upcoming_by_batch.get(b.id, []),
            }
        )

    plans = list(Plan.objects.filter(is_active=True).order_by("level"))

    return render(
        request,
        "trainers/live.html",
        {
            "rows": rows,
            "today_name": today.strftime("%A"),
            "has_batches": bool(rows),
            "plans": plans,
        },
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
        with transaction.atomic():
            lc = LiveClass.objects.create(
                batch=slot.batch,
                title=f"{slot.batch.name} · {slot.get_weekday_display()} live class",
                start_time=timezone.now(),
                duration_minutes=slot.duration_minutes,
                status=LiveClass.Status.LIVE,
                meet_link=request.POST.get("meet_link", "").strip(),
            )
            lc.allowed_plans.set(_selected_plans(request, slot))
            ensure_meet_link(lc)  # synchronous; reads allowed_plans we just set

    if lc.meet_link:
        return redirect(lc.meet_link)
    messages.warning(
        request,
        "Class started, but the Google Meet link couldn't be generated. "
        "Connect Google above (or add a link to this class) so students can join.",
    )
    return redirect("trainers:live")


def _selected_plans(request, slot):
    """Plans the trainer ticked for this link; default to the slot's plans."""
    ids = request.POST.getlist("plans")
    if ids:
        return list(Plan.objects.filter(id__in=ids, is_active=True))
    return list(slot.allowed_plans.all())


def _next_occurrence(slot, now):
    """Next future datetime for this weekly slot's weekday + time (aware)."""
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    days_ahead = (slot.weekday - today.weekday()) % 7
    date = today + datetime.timedelta(days=days_ahead)
    start = timezone.make_aware(datetime.datetime.combine(date, slot.start_time), tz)
    if start <= now:
        start += datetime.timedelta(days=7)  # slot time already passed this week
    return start


@trainer_required
def schedule_live(request, slot_id):
    """Schedule the next occurrence of a weekly slot as an upcoming class.

    Honors the admin weekday gating (you can only schedule existing slots). The
    Meet link + student Calendar invites are created by the post_save signal.
    """
    if request.method != "POST":
        return redirect("trainers:live")
    slot = get_object_or_404(
        BatchScheduleSlot.objects.select_related("batch", "batch__course"), pk=slot_id
    )
    if not _can_teach(request.user, slot.batch):
        raise PermissionDenied("You don't conduct this batch.")

    start = _next_occurrence(slot, timezone.now())

    # Don't double-book the same slot occurrence.
    existing = LiveClass.objects.filter(
        batch=slot.batch, start_time=start
    ).exclude(status=LiveClass.Status.CANCELLED).first()
    if existing:
        messages.info(
            request,
            f"A class is already scheduled for {start.strftime('%a %d %b, %I:%M %p')}.",
        )
        return redirect("trainers:live")

    with transaction.atomic():
        lc = LiveClass.objects.create(
            batch=slot.batch,
            title=f"{slot.batch.name} · {slot.get_weekday_display()} live class",
            start_time=start,
            duration_minutes=slot.duration_minutes,
            status=LiveClass.Status.SCHEDULED,
        )
        lc.allowed_plans.set(_selected_plans(request, slot))
        ensure_meet_link(lc)  # synchronous; reads allowed_plans we just set

    when = start.strftime("%a %d %b, %I:%M %p")
    if lc.meet_link:
        messages.success(
            request,
            f"Class scheduled for {when}. Eligible students have been invited "
            "with the Google Meet link.",
        )
    else:
        messages.warning(
            request,
            f"Class scheduled for {when}, but the Google Meet link couldn't be "
            "generated. Connect Google above (or add a link from the admin) so students can join.",
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
