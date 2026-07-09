import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from classroom.models import LiveClass

from . import razorpay_api
from .access import (
    can_access,
    get_enrollment,
    preview_count,
    unlocked_lecture_ids,
    unlocked_lesson_ids,
)
from .models import (
    Batch,
    BatchEnrollment,
    CourseEnrollment,
    LectureProgress,
    Lesson,
    LessonProgress,
    Payment,
    Plan,
)


@login_required
def dashboard(request):
    """Student home: batches, progress, next live class and lessons to resume.

    Trainers don't have a student dashboard — send them to Trainer Studio.
    """
    if getattr(request.user, "role", None) == "instructor":
        return redirect("trainers:dashboard")
    enrollments = list(
        BatchEnrollment.objects.filter(student=request.user, is_active=True)
        .select_related("batch", "batch__course", "plan")
        .order_by("-enrolled_at")
    )
    plan_by_batch = {e.batch_id: e.plan for e in enrollments}

    # Lessons this student has finished watching (for real completion %).
    completed_ids = set(
        LessonProgress.objects.filter(student=request.user, completed=True).values_list(
            "lesson_id", flat=True
        )
    )

    # Per-batch cards with accessible/completed lesson counts + a resume target.
    batch_cards = []
    lessons_available = 0
    lessons_done = 0
    continue_lesson = None
    has_provisional = False
    for e in enrollments:
        lessons = list(e.batch.lessons.all())
        unlocked = unlocked_lesson_ids(e, lessons)
        accessible = [l for l in lessons if l.id in unlocked]
        total, acc = len(lessons), len(accessible)
        if e.is_provisional:
            has_provisional = True
        done = sum(1 for l in accessible if l.id in completed_ids)
        lessons_available += acc
        lessons_done += done
        batch_cards.append(
            {
                "batch": e.batch,
                "plan": e.plan,
                "total": total,
                "accessible": acc,
                "locked": total - acc,
                "completed": done,
                "provisional": e.is_provisional,
                # Real progress: how much of the accessible content is finished.
                "pct": round(done / acc * 100) if acc else 0,
            }
        )
        # Resume at the first unfinished accessible lesson (else the first one).
        if continue_lesson is None and accessible:
            nxt = next((l for l in accessible if l.id not in completed_ids), accessible[0])
            continue_lesson = {"lesson": nxt, "batch": e.batch}

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

    # Whether the student is already on the highest available plan (hide "Upgrade").
    is_top_plan = False
    if top_plan is not None:
        max_level = (
            Plan.objects.filter(is_active=True)
            .order_by("-level")
            .values_list("level", flat=True)
            .first()
        )
        is_top_plan = max_level is not None and top_plan.level >= max_level

    # Homework the student hasn't submitted yet (shown until they submit).
    pending_homework = []
    if plan_by_batch:
        from homework.models import HomeTask, HomeworkSubmission

        tasks = (
            HomeTask.objects.filter(live_class__batch_id__in=plan_by_batch.keys())
            .select_related("live_class", "live_class__batch")
            .prefetch_related("allowed_plans")
            .order_by("-created_at")
        )
        submitted = set(
            HomeworkSubmission.objects.filter(student=request.user).values_list(
                "hometask_id", flat=True
            )
        )
        pending_homework = [
            t
            for t in tasks
            if t.is_open_to(plan_by_batch.get(t.live_class.batch_id)) and t.id not in submitted
        ]

    # Enrolled recorded (Udemy-style) courses with real watch progress.
    course_cards = []
    course_enrollments = list(
        CourseEnrollment.objects.filter(student=request.user, is_active=True).select_related(
            "course"
        )
    )
    if course_enrollments:
        done_lectures = set(
            LectureProgress.objects.filter(student=request.user, completed=True).values_list(
                "lecture_id", flat=True
            )
        )
        for ce in course_enrollments:
            ordered = ce.course.ordered_lectures()
            unlocked = unlocked_lecture_ids(ce, ordered)
            accessible = [lec for lec in ordered if lec.id in unlocked]
            total = len(accessible)
            done = sum(1 for lec in accessible if lec.id in done_lectures)
            resume = next((lec for lec in accessible if lec.id not in done_lectures), None)
            if resume is None and accessible:
                resume = accessible[0]
            course_cards.append(
                {
                    "course": ce.course,
                    "completed": done,
                    "total": total,
                    "pct": round(done / total * 100) if total else 0,
                    "provisional": ce.is_provisional,
                    "resume": resume,
                }
            )

    return render(
        request,
        "courses/dashboard.html",
        {
            "enrollments": enrollments,
            "batch_cards": batch_cards,
            "course_cards": course_cards,
            "upcoming": upcoming,
            "next_class": next_class,
            "continue_lesson": continue_lesson,
            "top_plan": top_plan,
            "is_top_plan": is_top_plan,
            "has_provisional": has_provisional,
            "pending_homework": pending_homework,
            "stats": {
                "batches": len(enrollments),
                "lessons": lessons_available,
                "lessons_completed": lessons_done,
                "upcoming": upcoming_count,
            },
        },
    )


def _batch_content(request, batch):
    """Shared: gather a batch's classes & lessons annotated with lock state."""
    enrollment = get_enrollment(request.user, batch)

    live_classes = (
        batch.live_classes.exclude(status=LiveClass.Status.CANCELLED)
        .prefetch_related("allowed_plans")
        .order_by("start_time")
    )
    lessons = list(batch.lessons.select_related("required_plan").all())

    plan = enrollment.plan if enrollment else None
    unlocked = unlocked_lesson_ids(enrollment, lessons)
    classes_view = [{"obj": c, "unlocked": c.is_open_to(plan)} for c in live_classes]
    lessons_view = [{"obj": l, "unlocked": l.id in unlocked} for l in lessons]
    return enrollment, classes_view, lessons_view


def _fmt_hm(seconds):
    """'3h 20m' / '45m' from a total number of seconds (blank if zero)."""
    if not seconds:
        return ""
    m = seconds // 60
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def catalog(request):
    """Public price/catalog page — recorded (self-paced) courses available to buy.

    This is the URL to link from the marketing site (fighterbulls.in); no login
    is required to browse courses and see prices.
    """
    plans = list(Plan.objects.filter(is_active=True).order_by("level"))
    min_price = min((int(p.price) for p in plans), default=0)
    batches = (
        Batch.objects.filter(is_self_paced=True, is_active=True, course__is_published=True)
        .select_related("course")
        .prefetch_related("lessons")
        .order_by("-created_at")
    )
    owned = set()
    if request.user.is_authenticated:
        owned = set(
            BatchEnrollment.objects.filter(student=request.user, is_active=True).values_list(
                "batch_id", flat=True
            )
        )
    cards = [
        {
            "batch": b,
            "lesson_count": len(b.lessons.all()),
            "duration": _fmt_hm(sum(l.duration_seconds for l in b.lessons.all())),
            "owned": b.id in owned,
        }
        for b in batches
    ]
    return render(request, "courses/catalog.html", {"cards": cards, "min_price": min_price})


def _course_landing(request, batch):
    """Udemy-style landing/preview for a self-paced course the student hasn't
    bought yet: the curriculum (locked) plus plans to enroll."""
    plans = list(Plan.objects.filter(is_active=True).order_by("level"))
    lessons = list(batch.lessons.select_related("required_plan").all())
    return render(
        request,
        "courses/batch_landing.html",
        {
            "batch": batch,
            "lessons": lessons,
            "lesson_count": len(lessons),
            "total_duration": _fmt_hm(sum(l.duration_seconds for l in lessons)),
            "options": [{"plan": p, "amount": int(p.price)} for p in plans],
            "min_price": min((int(p.price) for p in plans), default=0),
        },
    )


def batch_detail(request, code):
    batch = get_object_or_404(Batch, code=code, is_active=True)
    enrollment = get_enrollment(request.user, batch)
    if enrollment is None:
        # Self-paced courses show a public buy page; live batches stay private.
        if batch.is_self_paced:
            return _course_landing(request, batch)
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        return render(request, "courses/not_enrolled.html", {"batch": batch}, status=403)

    _, classes_view, lessons_view = _batch_content(request, batch)

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
            "is_provisional": enrollment.is_provisional,
            "preview_count": preview_count(),
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
    unlocked = unlocked_lesson_ids(enrollment, lessons)
    # This student's progress across the batch (for playlist ticks + resume).
    progress = {
        p.lesson_id: p
        for p in LessonProgress.objects.filter(student=request.user, lesson__batch=batch)
    }
    annotated = [
        {
            "obj": l,
            "unlocked": l.id in unlocked,
            "completed": l.id in progress and progress[l.id].completed,
        }
        for l in lessons
    ]
    accessible = [l for l in lessons if l.id in unlocked]
    a_idx = next((i for i, l in enumerate(accessible) if l.pk == lesson.pk), 0)
    this_progress = progress.get(lesson.id)
    return render(
        request,
        "courses/lesson.html",
        {
            "batch": batch,
            "lesson": lesson,
            "lessons": annotated,
            "resume_position": this_progress.position_seconds if this_progress else 0,
            "is_completed": bool(this_progress and this_progress.completed),
            "prev_lesson": accessible[a_idx - 1] if a_idx > 0 else None,
            "next_lesson": accessible[a_idx + 1] if a_idx < len(accessible) - 1 else None,
        },
    )


@login_required
@require_POST
def lesson_progress(request, code, pk):
    """Save a student's watch position for a lesson (called by the player).

    Accepts ``position`` (seconds) and optional ``completed=1``. Access is gated
    exactly like the video source, so progress can only be saved for lessons the
    student may actually watch.
    """
    batch = get_object_or_404(Batch, code=code, is_active=True)
    lesson = get_object_or_404(Lesson, pk=pk, batch=batch)
    enrollment = get_enrollment(request.user, batch)
    if not can_access(enrollment, lesson):
        raise Http404("Not available.")

    try:
        position = max(0, int(float(request.POST.get("position", 0))))
    except (TypeError, ValueError):
        position = 0

    prog, _ = LessonProgress.objects.get_or_create(student=request.user, lesson=lesson)
    prog.position_seconds = position
    # Completion only ever latches on — never un-completes on a re-watch.
    if request.POST.get("completed") == "1":
        prog.completed = True
    prog.save(update_fields=["position_seconds", "completed", "updated_at"])
    return JsonResponse({"ok": True, "completed": prog.completed})


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


# ---------------------------------------------------------------------------
# Recorded-course checkout — manual UPI + Razorpay online
# ---------------------------------------------------------------------------
def _amount_for(enrollment, plan):
    """Rupees to charge for ``plan``: the upgrade difference when the student is
    already enrolled on a lower tier, else the plan's full price."""
    if enrollment and enrollment.plan.level < plan.level:
        return max(int(plan.price - enrollment.plan.price), 0)
    return int(plan.price)


def _upi_links(amount, note):
    """UPI deep links for a payment — a generic one plus app-specific schemes.

    On a phone these open the chosen app straight to a pre-filled payment; on
    desktop they do nothing (the QR is the fallback there).
    """
    from urllib.parse import urlencode

    from .payment_config import payment_config

    cfg = payment_config()
    query = urlencode(
        {
            "pa": cfg.upi_vpa,
            "pn": cfg.upi_payee_name,
            "am": f"{amount}",
            "cu": "INR",
            "tn": note[:50],
        }
    )
    return {
        "generic": "upi://pay?" + query,
        "gpay": "tez://upi/pay?" + query,
        "phonepe": "phonepe://pay?" + query,
        "paytm": "paytmmp://pay?" + query,
    }


def _qr_data_uri(data):
    """Render ``data`` as a QR PNG returned as a base64 data URI (self-contained)."""
    import base64
    import io

    import qrcode

    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _register_student(request, data):
    """Create + log in a student account from checkout form data.

    Returns (user, None) on success or (None, error_message). Used only for the
    public course-checkout flow (accounts are otherwise admin-created).
    """
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()
    name = (data.get("name") or "").strip()

    if not email or not password:
        return None, "Please enter your email and choose a password."

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        return None, "An account with this email already exists — please log in instead."

    try:
        validate_password(password)
    except ValidationError as exc:
        return None, " ".join(exc.messages)

    first, _, last = name.partition(" ")
    user = User.objects.create_user(
        email=email,
        password=password,
        role="student",
        first_name=first,
        last_name=last,
        phone=phone,
    )
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return user, None


@require_POST
def checkout_register(request, code):
    """Public checkout step 1: create the visitor's account, then continue to pay."""
    batch = get_object_or_404(Batch, code=code, is_active=True)
    plan = get_object_or_404(Plan, slug=request.POST.get("plan"), is_active=True)
    back = f"{reverse('courses:checkout', args=[code])}?plan={plan.slug}"

    if request.user.is_authenticated:
        return redirect(back)

    user, error = _register_student(request, request.POST)
    if error:
        return render(
            request,
            "courses/checkout_register.html",
            {
                "batch": batch,
                "plan": plan,
                "amount": _amount_for(None, plan),
                "login_next": back,
                "error": error,
                "form": {
                    "name": request.POST.get("name", ""),
                    "email": request.POST.get("email", ""),
                    "phone": request.POST.get("phone", ""),
                },
            },
        )
    messages.success(request, "Account created — complete your payment below to enroll.")
    return redirect(back)


def checkout(request, code):
    """Buy access to a batch on a chosen plan (Basic/Advance/…).

    Public: a visitor from the marketing site can reach this without an account.
    Without ``?plan=`` it shows a plan chooser; with a plan, a logged-out visitor
    is asked to create an account first, then lands on the payment page (manual
    UPI QR + Razorpay button, whichever are configured).
    """
    batch = get_object_or_404(Batch, code=code, is_active=True)
    plans = list(Plan.objects.filter(is_active=True).order_by("level"))
    enrollment = get_enrollment(request.user, batch)
    current_level = enrollment.plan.level if enrollment else -1

    plan = next((p for p in plans if p.slug == request.GET.get("plan")), None)

    if plan is None:
        options = [
            {"plan": p, "amount": _amount_for(enrollment, p)}
            for p in plans
            if p.level > current_level
        ]
        return render(
            request,
            "courses/checkout_choose.html",
            {"batch": batch, "options": options, "enrollment": enrollment},
        )

    # Already have this (or higher) access — nothing to buy.
    if plan.level <= current_level:
        return redirect(batch.get_absolute_url())

    amount = _amount_for(enrollment, plan)

    # Logged-out visitor: create an account before paying.
    if not request.user.is_authenticated:
        return render(
            request,
            "courses/checkout_register.html",
            {
                "batch": batch,
                "plan": plan,
                "amount": amount,
                "login_next": f"{reverse('courses:checkout', args=[code])}?plan={plan.slug}",
                "form": {},
            },
        )

    from .payment_config import payment_config

    cfg = payment_config()
    upi = None
    if cfg.upi_vpa and amount > 0:
        links = _upi_links(amount, f"{batch.code} {plan.slug}")
        upi = {
            "vpa": cfg.upi_vpa,
            "payee": cfg.upi_payee_name,
            "links": links,
            "qr": _qr_data_uri(links["generic"]),
        }

    return render(
        request,
        "courses/checkout.html",
        {
            "batch": batch,
            "plan": plan,
            "amount": amount,
            "enrollment": enrollment,
            "upi": upi,
            "preview_count": preview_count(),
            "razorpay_enabled": cfg.razorpay_enabled,
            "razorpay_key_id": cfg.razorpay_key_id,
        },
    )


def _resolve_purchase(request, code):
    """Shared guard for checkout POSTs: return (batch, plan, enrollment, amount).

    Raises Http404 for an unknown batch/plan; returns ``amount`` of 0 (caller
    should reject) when the student already has equal-or-higher access.
    """
    batch = get_object_or_404(Batch, code=code, is_active=True)
    plan = get_object_or_404(Plan, slug=request.POST.get("plan"), is_active=True)
    enrollment = get_enrollment(request.user, batch)
    current_level = enrollment.plan.level if enrollment else -1
    amount = 0 if plan.level <= current_level else _amount_for(enrollment, plan)
    return batch, plan, enrollment, amount


@login_required
@require_POST
def upi_submit(request, code):
    """Record a manual-UPI payment (reference and/or screenshot) for admin review.

    The student must provide at least one proof of payment — a transaction / UTR
    number or a screenshot. On submit they get provisional preview access to the
    first few lessons; full access follows once an admin verifies the payment.
    """
    batch, plan, enrollment, amount = _resolve_purchase(request, code)
    if amount <= 0:
        return redirect(batch.get_absolute_url())

    reference = (request.POST.get("upi_reference") or "").strip()
    screenshot = request.FILES.get("screenshot")
    if not reference and not screenshot:
        messages.error(
            request,
            "Please enter your UPI transaction/UTR number or upload a payment screenshot.",
        )
        return redirect(f"{reverse('courses:checkout', args=[code])}?plan={plan.slug}")

    payment = Payment.objects.create(
        student=request.user,
        batch=batch,
        plan=plan,
        amount=amount,
        method=Payment.Method.MANUAL_UPI,
        status=Payment.Status.PENDING,
        upi_reference=reference,
        screenshot=screenshot,
    )
    payment.grant_provisional_access()
    return render(
        request,
        "courses/checkout_pending.html",
        {"batch": batch, "plan": plan, "preview_count": preview_count()},
    )


@login_required
@require_POST
def razorpay_order(request, code):
    """Create a Razorpay order (+ a pending Payment) for the online checkout."""
    from .payment_config import payment_config

    cfg = payment_config()
    if not cfg.razorpay_enabled:
        return JsonResponse({"error": "Online payment is not available."}, status=400)

    batch, plan, enrollment, amount = _resolve_purchase(request, code)
    if amount <= 0:
        return JsonResponse({"error": "You already have this access."}, status=400)

    payment = Payment.objects.create(
        student=request.user,
        batch=batch,
        plan=plan,
        amount=amount,
        method=Payment.Method.RAZORPAY,
        status=Payment.Status.CREATED,
    )
    try:
        order = razorpay_api.create_order(
            amount * 100,
            receipt=f"pay_{payment.id}",
            notes={"payment_id": str(payment.id), "batch": batch.code, "plan": plan.slug},
        )
    except Exception:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        return JsonResponse({"error": "Could not start the payment. Please try again."}, status=502)

    payment.razorpay_order_id = order["id"]
    payment.save(update_fields=["razorpay_order_id"])
    return JsonResponse(
        {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": "INR",
            "key_id": cfg.razorpay_key_id,
            "name": cfg.upi_payee_name,
            "description": f"{batch.name} · {plan.name}",
            "prefill": {
                "name": request.user.display_name,
                "email": request.user.email,
                "contact": request.user.phone,
            },
        }
    )


@login_required
@require_POST
def razorpay_verify(request, code):
    """Verify the checkout callback signature and unlock access immediately.

    This is the browser-side confirmation; the webhook is the authoritative one
    and safely re-runs the same idempotent ``mark_paid``.
    """
    order_id = request.POST.get("razorpay_order_id")
    payment_id = request.POST.get("razorpay_payment_id")
    signature = request.POST.get("razorpay_signature")
    payment = get_object_or_404(Payment, razorpay_order_id=order_id, student=request.user)

    if not razorpay_api.verify_checkout_signature(order_id, payment_id, signature):
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        return JsonResponse({"ok": False, "error": "Payment could not be verified."}, status=400)

    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature
    payment.save(update_fields=["razorpay_payment_id", "razorpay_signature"])
    payment.mark_paid()
    return JsonResponse({"ok": True, "redirect": payment.batch.get_absolute_url()})


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Authoritative payment confirmation from Razorpay (server-to-server).

    Verifies the signature, then unlocks access on ``payment.captured`` /
    ``order.paid``. Idempotent: a repeat delivery is a no-op.
    """
    signature = request.headers.get("X-Razorpay-Signature", "")
    raw = request.body
    if not razorpay_api.verify_webhook_signature(raw, signature):
        return HttpResponseBadRequest("invalid signature")

    try:
        event = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid payload")

    if event.get("event") in ("payment.captured", "order.paid"):
        payload = event.get("payload", {})
        entity = payload.get("payment", {}).get("entity", {})
        order_id = entity.get("order_id") or payload.get("order", {}).get("entity", {}).get("id")
        if order_id:
            payment = Payment.objects.filter(razorpay_order_id=order_id).first()
            if payment:
                if entity.get("id"):
                    payment.razorpay_payment_id = entity["id"]
                    payment.save(update_fields=["razorpay_payment_id"])
                payment.mark_paid()
    return JsonResponse({"ok": True})
