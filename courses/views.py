from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from classroom.models import LiveClass

from .access import can_access, get_enrollment
from .models import Batch, BatchEnrollment, Lesson, Plan


@login_required
def dashboard(request):
    """Student home: batches, progress, next live class and lessons to resume."""
    enrollments = list(
        BatchEnrollment.objects.filter(student=request.user, is_active=True)
        .select_related("batch", "batch__course", "plan")
        .order_by("-enrolled_at")
    )
    plan_by_batch = {e.batch_id: e.plan for e in enrollments}

    # Per-batch cards with accessible/total lesson counts + a resume target.
    batch_cards = []
    lessons_available = 0
    continue_lesson = None
    for e in enrollments:
        lessons = list(e.batch.lessons.all())
        accessible = [l for l in lessons if e.plan.level >= l.required_level]
        total, acc = len(lessons), len(accessible)
        lessons_available += acc
        batch_cards.append(
            {
                "batch": e.batch,
                "plan": e.plan,
                "total": total,
                "accessible": acc,
                "locked": total - acc,
                "pct": round(acc / total * 100) if total else 0,
            }
        )
        if continue_lesson is None and accessible:
            continue_lesson = {"lesson": accessible[0], "batch": e.batch}

    # Upcoming classes across all batches, tagged with unlock state.
    upcoming, next_class, upcoming_count = [], None, 0
    if plan_by_batch:
        classes = (
            LiveClass.objects.filter(batch_id__in=plan_by_batch.keys())
            .exclude(status=LiveClass.Status.CANCELLED)
            .filter(start_time__gte=timezone.now() - timezone.timedelta(hours=2))
            .select_related("batch")
            .prefetch_related("allowed_plans")
            .order_by("start_time")[:12]
        )
        for lc in classes:
            unlocked = lc.is_open_to(plan_by_batch[lc.batch_id])
            upcoming.append({"obj": lc, "unlocked": unlocked})
            if unlocked and lc.live_state in ("upcoming", "live"):
                upcoming_count += 1
                if next_class is None:
                    next_class = lc

    top_plan = max((e.plan for e in enrollments), key=lambda p: p.level, default=None)

    return render(
        request,
        "courses/dashboard.html",
        {
            "enrollments": enrollments,
            "batch_cards": batch_cards,
            "upcoming": upcoming,
            "next_class": next_class,
            "continue_lesson": continue_lesson,
            "top_plan": top_plan,
            "stats": {
                "batches": len(enrollments),
                "lessons": lessons_available,
                "upcoming": upcoming_count,
            },
        },
    )


def _batch_content(request, batch):
    """Shared: gather a batch's classes & lessons annotated with lock state."""
    enrollment = get_enrollment(request.user, batch)
    plan_level = enrollment.plan.level if enrollment else -1

    live_classes = (
        batch.live_classes.exclude(status=LiveClass.Status.CANCELLED)
        .prefetch_related("allowed_plans")
        .order_by("start_time")
    )
    lessons = batch.lessons.select_related("required_plan").all()

    plan = enrollment.plan if enrollment else None
    classes_view = [{"obj": c, "unlocked": c.is_open_to(plan)} for c in live_classes]
    lessons_view = [{"obj": l, "unlocked": plan_level >= l.required_level} for l in lessons]
    return enrollment, classes_view, lessons_view


@login_required
def batch_detail(request, code):
    batch = get_object_or_404(Batch, code=code, is_active=True)
    enrollment, classes_view, lessons_view = _batch_content(request, batch)
    if enrollment is None:
        return render(request, "courses/not_enrolled.html", {"batch": batch}, status=403)

    lessons_total = len(lessons_view)
    lessons_unlocked = sum(1 for l in lessons_view if l["unlocked"])
    classes_unlocked = sum(1 for c in classes_view if c["unlocked"])
    return render(
        request,
        "courses/batch_detail.html",
        {
            "batch": batch,
            "enrollment": enrollment,
            "classes_view": classes_view,
            "lessons_view": lessons_view,
            "stats": {
                "lessons_total": lessons_total,
                "lessons_unlocked": lessons_unlocked,
                "lessons_locked": lessons_total - lessons_unlocked,
                "lessons_pct": round(lessons_unlocked / lessons_total * 100) if lessons_total else 0,
                "classes_total": len(classes_view),
                "classes_unlocked": classes_unlocked,
            },
        },
    )


@login_required
def lesson_view(request, code, pk):
    batch = get_object_or_404(Batch, code=code, is_active=True)
    lesson = get_object_or_404(Lesson, pk=pk, batch=batch)
    enrollment = get_enrollment(request.user, batch)

    if enrollment is None:
        return render(request, "courses/not_enrolled.html", {"batch": batch}, status=403)
    if not can_access(enrollment, lesson):
        return render(
            request,
            "courses/locked.html",
            {"batch": batch, "item": lesson, "kind": "video"},
            status=403,
        )

    lessons = list(batch.lessons.select_related("required_plan").all())
    annotated = [{"obj": l, "unlocked": enrollment.plan.level >= l.required_level} for l in lessons]
    idx = next((i for i, l in enumerate(lessons) if l.pk == lesson.pk), 0)
    accessible = [l for l in lessons if enrollment.plan.level >= l.required_level]
    a_idx = next((i for i, l in enumerate(accessible) if l.pk == lesson.pk), 0)
    return render(
        request,
        "courses/lesson.html",
        {
            "batch": batch,
            "lesson": lesson,
            "lessons": annotated,
            "prev_lesson": accessible[a_idx - 1] if a_idx > 0 else None,
            "next_lesson": accessible[a_idx + 1] if a_idx < len(accessible) - 1 else None,
        },
    )


@login_required
def lesson_source(request, code, pk):
    """Auth + plan gated video source for the branded player."""
    batch = get_object_or_404(Batch, code=code, is_active=True)
    lesson = get_object_or_404(Lesson, pk=pk, batch=batch)
    enrollment = get_enrollment(request.user, batch)
    if not can_access(enrollment, lesson):
        raise Http404("Not available.")
    return JsonResponse(
        {"videoId": lesson.youtube_id, "title": lesson.title, "duration": lesson.duration_seconds}
    )


def pricing(request):
    """Public pricing page. Each plan's CTA opens WhatsApp with a message
    pre-filled from the logged-in student's profile (name, email, current plan,
    batch) plus the plan they want to upgrade to."""
    from urllib.parse import urlencode

    from django.conf import settings

    plans = list(Plan.objects.filter(is_active=True).order_by("level"))
    phone = getattr(settings, "WHATSAPP_PHONE", "917029490341")

    user = request.user
    name = email = current_plan = batches = ""
    current_level = current_price = None
    if user.is_authenticated:
        name = user.display_name
        email = user.email
        enrolls = list(
            BatchEnrollment.objects.filter(student=user, is_active=True)
            .select_related("batch", "plan")
        )
        if enrolls:
            top = max(enrolls, key=lambda e: e.plan.level)
            current_plan = top.plan.name
            current_level = top.plan.level
            current_price = top.plan.price
            batches = ", ".join(sorted({e.batch.name for e in enrolls}))

    cards = []
    for p in plans:
        term = f"{p.duration_months} Month" + ("s" if p.duration_months != 1 else "")
        is_current = current_level is not None and p.level == current_level
        is_upgrade = current_level is not None and p.level > current_level
        is_lower = current_level is not None and p.level < current_level
        # Amount shown/charged: the difference to upgrade, else the full price.
        amount_value = int(p.price - current_price) if is_upgrade else int(p.price)
        full_price = f"₹{int(p.price):,}"

        if is_upgrade:
            text = "\n".join([
                f"Hi Fighter Bull's! I want to upgrade from *{current_plan}* to *{p.name}*.",
                f"Upgrade amount (difference): ₹{amount_value:,}  (full {full_price} − {current_plan} ₹{int(current_price):,})",
                "",
                f"Name: {name or '-'}",
                f"Email: {email or '-'}",
                f"Current plan: {current_plan or '-'}",
                f"Batch: {batches or '-'}",
            ])
        elif is_current:
            text = "\n".join([
                f"Hi Fighter Bull's! I'm on the *{p.name}* plan and have a question.",
                "",
                f"Name: {name or '-'}",
                f"Email: {email or '-'}",
                f"Batch: {batches or '-'}",
            ])
        elif user.is_authenticated:
            text = "\n".join([
                f"Hi Fighter Bull's! I'm interested in the *{p.name}* plan ({full_price} / {term}).",
                "",
                f"Name: {name or '-'}",
                f"Email: {email or '-'}",
                f"Current plan: {current_plan or '-'}",
                f"Batch: {batches or '-'}",
            ])
        else:
            text = (
                f"Hi Fighter Bull's! I'm interested in the *{p.name}* course "
                f"({full_price} / {term}). Please share the next steps."
            )
        params = {"phone": phone, "text": text, "type": "phone_number", "app_absent": "0"}
        cards.append({
            "plan": p,
            "wa_url": "https://api.whatsapp.com/send/?" + urlencode(params),
            "is_current": is_current,
            "is_upgrade": is_upgrade,
            "is_lower": is_lower,
            "amount_value": amount_value,
        })

    return render(
        request,
        "courses/pricing.html",
        {"plan_cards": cards, "current_plan": current_plan},
    )
