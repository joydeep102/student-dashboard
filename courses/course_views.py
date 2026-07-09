"""Public + student views for Udemy-style recorded courses.

Catalog → course landing (with free previews) → checkout (self-register + pay) →
learn (branded player, curriculum sidebar, progress/resume). Payment mirrors the
batch flow: manual UPI (with provisional preview) and Razorpay online.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import json

from . import razorpay_api
from .access import (
    can_watch_lecture,
    get_course_enrollment,
    preview_count,
    unlocked_lecture_ids,
)
from .models import CourseEnrollment, CoursePayment, Lecture, LectureProgress, RecordedCourse
from .payment_config import payment_config
from .views import _qr_data_uri, _register_student, _upi_links


def _published_course(slug):
    return get_object_or_404(RecordedCourse, slug=slug, is_published=True)


def _curriculum(course, enrollment, progress_by_lecture=None):
    """Sections annotated with their lectures' unlock + completion state."""
    ordered = course.ordered_lectures()
    unlocked = unlocked_lecture_ids(enrollment, ordered)
    progress_by_lecture = progress_by_lecture or {}
    sections = []
    for section in course.sections.prefetch_related("lectures").all():
        rows = []
        for lec in section.lectures.all():
            rows.append(
                {
                    "obj": lec,
                    "unlocked": lec.id in unlocked,
                    "preview": lec.is_preview,
                    "completed": bool(
                        progress_by_lecture.get(lec.id)
                        and progress_by_lecture[lec.id].completed
                    ),
                }
            )
        sections.append({"obj": section, "lectures": rows})
    return sections, ordered, unlocked


# ---------------------------------------------------------------------------
# Catalog + landing (public)
# ---------------------------------------------------------------------------
def catalog(request):
    """Public price/catalog page — the URL to link from fighterbulls.in."""
    courses = (
        RecordedCourse.objects.filter(is_published=True)
        .select_related("instructor")
        .order_by("-created_at")
    )
    owned = set()
    if request.user.is_authenticated:
        owned = set(
            CourseEnrollment.objects.filter(
                student=request.user, is_active=True
            ).values_list("course_id", flat=True)
        )
    cards = [
        {
            "course": c,
            "lectures": c.lecture_count,
            "duration": c.duration_display,
            "owned": c.id in owned,
        }
        for c in courses
    ]
    return render(request, "courses/catalog.html", {"cards": cards})


def course_landing(request, slug):
    """Udemy-style course page: curriculum with free previews + a buy box.

    Enrolled students are sent straight into the course to keep watching.
    """
    course = _published_course(slug)
    enrollment = get_course_enrollment(request.user, course)
    if enrollment and not enrollment.is_provisional:
        first = next(iter(course.ordered_lectures()), None)
        if first:
            return redirect("courses:learn", slug=course.slug, pk=first.pk)

    sections, ordered, _ = _curriculum(course, enrollment)
    return render(
        request,
        "courses/course_landing.html",
        {
            "course": course,
            "sections": sections,
            "lecture_count": len(ordered),
            "enrollment": enrollment,
            "preview_count": preview_count(),
        },
    )


# ---------------------------------------------------------------------------
# Learn (watch a lecture)
# ---------------------------------------------------------------------------
def learn(request, slug, pk):
    course = _published_course(slug)
    lecture = get_object_or_404(Lecture, pk=pk, section__course=course)
    enrollment = get_course_enrollment(request.user, course)

    if not can_watch_lecture(request.user, lecture, enrollment):
        messages.info(request, "Enroll to unlock this lecture.")
        return redirect(course.get_absolute_url())

    progress_by_lecture = {}
    resume_position, is_completed = 0, False
    if request.user.is_authenticated:
        progress_by_lecture = {
            p.lecture_id: p
            for p in LectureProgress.objects.filter(
                student=request.user, lecture__section__course=course
            )
        }
        this = progress_by_lecture.get(lecture.id)
        resume_position = this.position_seconds if this else 0
        is_completed = bool(this and this.completed)

    sections, ordered, unlocked = _curriculum(course, enrollment, progress_by_lecture)
    watchable = [lec for lec in ordered if lec.id in unlocked]
    idx = next((i for i, lec in enumerate(watchable) if lec.pk == lecture.pk), 0)

    return render(
        request,
        "courses/learn.html",
        {
            "course": course,
            "lecture": lecture,
            "sections": sections,
            "enrollment": enrollment,
            "resume_position": resume_position,
            "is_completed": is_completed,
            "prev_lecture": watchable[idx - 1] if idx > 0 else None,
            "next_lecture": watchable[idx + 1] if idx < len(watchable) - 1 else None,
        },
    )


def lecture_source(request, slug, pk):
    """Auth + access gated video source for the branded player."""
    course = _published_course(slug)
    lecture = get_object_or_404(Lecture, pk=pk, section__course=course)
    enrollment = get_course_enrollment(request.user, course)
    if not can_watch_lecture(request.user, lecture, enrollment):
        raise Http404("Not available.")
    return JsonResponse(
        {"videoId": lecture.youtube_id, "title": lecture.title,
         "duration": lecture.duration_seconds}
    )


@login_required
@require_POST
def lecture_progress(request, slug, pk):
    """Save a student's watch position for a lecture (called by the player)."""
    course = _published_course(slug)
    lecture = get_object_or_404(Lecture, pk=pk, section__course=course)
    enrollment = get_course_enrollment(request.user, course)
    if not can_watch_lecture(request.user, lecture, enrollment):
        raise Http404("Not available.")

    try:
        position = max(0, int(float(request.POST.get("position", 0))))
    except (TypeError, ValueError):
        position = 0
    prog, _ = LectureProgress.objects.get_or_create(student=request.user, lecture=lecture)
    prog.position_seconds = position
    if request.POST.get("completed") == "1":
        prog.completed = True
    prog.save(update_fields=["position_seconds", "completed", "updated_at"])
    return JsonResponse({"ok": True, "completed": prog.completed})


# ---------------------------------------------------------------------------
# Checkout — self-register (public) + pay (manual UPI / Razorpay)
# ---------------------------------------------------------------------------
def checkout(request, slug):
    """Buy a course. Logged-out visitors register first, then pay."""
    course = _published_course(slug)
    enrollment = get_course_enrollment(request.user, course)
    if enrollment and not enrollment.is_provisional:
        return redirect(course.get_absolute_url())

    amount = int(course.price)

    if not request.user.is_authenticated:
        return render(
            request,
            "courses/course_register.html",
            {
                "course": course,
                "amount": amount,
                "login_next": reverse("courses:course_checkout", args=[slug]),
                "form": {},
            },
        )

    cfg = payment_config()
    upi = None
    if cfg.upi_vpa and amount > 0:
        links = _upi_links(amount, f"course {course.slug}")
        upi = {"vpa": cfg.upi_vpa, "payee": cfg.upi_payee_name,
               "links": links, "qr": _qr_data_uri(links["generic"])}

    return render(
        request,
        "courses/course_checkout.html",
        {
            "course": course,
            "amount": amount,
            "upi": upi,
            "preview_count": preview_count(),
            "razorpay_enabled": cfg.razorpay_enabled,
            "razorpay_key_id": cfg.razorpay_key_id,
        },
    )


@require_POST
def checkout_register(request, slug):
    """Public checkout step 1: create the visitor's account, then continue to pay."""
    course = _published_course(slug)
    back = reverse("courses:course_checkout", args=[slug])
    if request.user.is_authenticated:
        return redirect(back)
    user, error = _register_student(request, request.POST)
    if error:
        return render(
            request,
            "courses/course_register.html",
            {
                "course": course,
                "amount": int(course.price),
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


def _already_full(user, course):
    e = get_course_enrollment(user, course)
    return e is not None and not e.is_provisional


@login_required
@require_POST
def upi_submit(request, slug):
    """Record a manual-UPI payment (reference and/or screenshot); grant preview."""
    course = _published_course(slug)
    if _already_full(request.user, course):
        return redirect(course.get_absolute_url())

    reference = (request.POST.get("upi_reference") or "").strip()
    screenshot = request.FILES.get("screenshot")
    if not reference and not screenshot:
        messages.error(
            request,
            "Please enter your UPI transaction/UTR number or upload a payment screenshot.",
        )
        return redirect(reverse("courses:course_checkout", args=[slug]))

    payment = CoursePayment.objects.create(
        student=request.user,
        course=course,
        amount=int(course.price),
        method=CoursePayment.Method.MANUAL_UPI,
        status=CoursePayment.Status.PENDING,
        upi_reference=reference,
        screenshot=screenshot,
    )
    payment.grant_provisional_access()
    return render(
        request,
        "courses/course_pending.html",
        {"course": course, "preview_count": preview_count()},
    )


@login_required
@require_POST
def razorpay_order(request, slug):
    """Create a Razorpay order (+ pending CoursePayment) for online checkout."""
    cfg = payment_config()
    if not cfg.razorpay_enabled:
        return JsonResponse({"error": "Online payment is not available."}, status=400)
    course = _published_course(slug)
    if _already_full(request.user, course):
        return JsonResponse({"error": "You already own this course."}, status=400)

    amount = int(course.price)
    payment = CoursePayment.objects.create(
        student=request.user, course=course, amount=amount,
        method=CoursePayment.Method.RAZORPAY, status=CoursePayment.Status.CREATED,
    )
    try:
        order = razorpay_api.create_order(
            amount * 100,
            receipt=f"course_{payment.id}",
            notes={"course_payment_id": str(payment.id), "course": course.slug},
        )
    except Exception:
        payment.status = CoursePayment.Status.FAILED
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
            "description": course.title,
            "prefill": {
                "name": request.user.display_name,
                "email": request.user.email,
                "contact": request.user.phone,
            },
        }
    )


@login_required
@require_POST
def razorpay_verify(request, slug):
    """Verify the checkout callback signature and unlock the course."""
    order_id = request.POST.get("razorpay_order_id")
    payment_id = request.POST.get("razorpay_payment_id")
    signature = request.POST.get("razorpay_signature")
    payment = get_object_or_404(
        CoursePayment, razorpay_order_id=order_id, student=request.user
    )
    if not razorpay_api.verify_checkout_signature(order_id, payment_id, signature):
        payment.status = CoursePayment.Status.FAILED
        payment.save(update_fields=["status"])
        return JsonResponse({"ok": False, "error": "Payment could not be verified."}, status=400)

    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature
    payment.save(update_fields=["razorpay_payment_id", "razorpay_signature"])
    payment.mark_paid()
    return JsonResponse({"ok": True, "redirect": payment.course.get_absolute_url()})


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Authoritative Razorpay confirmation for course payments."""
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
            payment = CoursePayment.objects.filter(razorpay_order_id=order_id).first()
            if payment:
                if entity.get("id"):
                    payment.razorpay_payment_id = entity["id"]
                    payment.save(update_fields=["razorpay_payment_id"])
                payment.mark_paid()
    return JsonResponse({"ok": True})
