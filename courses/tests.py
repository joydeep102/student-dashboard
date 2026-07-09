import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Batch, BatchEnrollment, Course, Lesson, LessonProgress, Payment, Plan

User = get_user_model()


class BaseData(TestCase):
    def setUp(self):
        self.basic = Plan.objects.create(name="Basic", level=1, price=1000)
        self.advance = Plan.objects.create(name="Advance", level=2, price=3000)
        self.course = Course.objects.create(title="Recorded Trading", is_published=True)
        self.batch = Batch.objects.create(course=self.course, name="Rec 01", is_self_paced=True)
        self.free_lesson = Lesson.objects.create(batch=self.batch, title="Intro", order=1)
        self.adv_lesson = Lesson.objects.create(
            batch=self.batch, title="Advanced setups", order=2, required_plan=self.advance,
            duration_seconds=600,
        )
        self.student = User.objects.create_user(
            email="s@test.com", password="pw12345!", role="student"
        )


class PaymentAccessTests(BaseData):
    def test_mark_paid_creates_enrollment(self):
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.basic, amount=1000,
            method=Payment.Method.MANUAL_UPI, status=Payment.Status.PENDING, upi_reference="X1",
        )
        pay.mark_paid()
        pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.Status.PAID)
        self.assertIsNotNone(pay.paid_at)
        e = BatchEnrollment.objects.get(student=self.student, batch=self.batch)
        self.assertEqual(e.plan, self.basic)
        self.assertTrue(e.is_active)

    def test_mark_paid_is_idempotent(self):
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.basic, amount=1000,
            method=Payment.Method.RAZORPAY,
        )
        pay.mark_paid()
        first_paid_at = Payment.objects.get(pk=pay.pk).paid_at
        pay.mark_paid()  # webhook + checkout callback both fire
        self.assertEqual(BatchEnrollment.objects.filter(student=self.student).count(), 1)
        self.assertEqual(Payment.objects.get(pk=pay.pk).paid_at, first_paid_at)

    def test_upgrade_never_downgrades(self):
        BatchEnrollment.objects.create(student=self.student, batch=self.batch, plan=self.advance)
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.basic, amount=0,
            method=Payment.Method.MANUAL_UPI,
        )
        pay.mark_paid()
        e = BatchEnrollment.objects.get(student=self.student, batch=self.batch)
        self.assertEqual(e.plan, self.advance)  # kept the higher tier


@override_settings(PROVISIONAL_PREVIEW_LESSONS=2)
class ProvisionalPreviewTests(BaseData):
    def test_provisional_limits_to_first_two_lessons(self):
        from .access import can_access

        l3 = Lesson.objects.create(batch=self.batch, title="Third", order=3)
        # Advance provisional enrollment: plan allows everything, preview caps at 2.
        e = BatchEnrollment.objects.create(
            student=self.student, batch=self.batch, plan=self.advance, is_provisional=True
        )
        self.assertTrue(can_access(e, self.free_lesson))   # 1st
        self.assertTrue(can_access(e, self.adv_lesson))    # 2nd
        self.assertFalse(can_access(e, l3))                # 3rd — locked until verified

    def test_full_enrollment_sees_everything(self):
        from .access import can_access

        l3 = Lesson.objects.create(batch=self.batch, title="Third", order=3)
        e = BatchEnrollment.objects.create(
            student=self.student, batch=self.batch, plan=self.advance, is_provisional=False
        )
        self.assertTrue(can_access(e, l3))

    def test_provisional_progress_blocked_beyond_preview(self):
        l3 = Lesson.objects.create(batch=self.batch, title="Third", order=3)
        BatchEnrollment.objects.create(
            student=self.student, batch=self.batch, plan=self.advance, is_provisional=True
        )
        self.client.force_login(self.student)
        url = reverse("courses:lesson_progress", args=[self.batch.code, l3.pk])
        self.assertEqual(self.client.post(url, {"position": "5"}).status_code, 404)


class ProgressTests(BaseData):
    def setUp(self):
        super().setUp()
        BatchEnrollment.objects.create(student=self.student, batch=self.batch, plan=self.basic)
        self.client.force_login(self.student)

    def _url(self, lesson):
        return reverse("courses:lesson_progress", args=[self.batch.code, lesson.pk])

    def test_saves_position(self):
        res = self.client.post(self._url(self.free_lesson), {"position": "42"})
        self.assertEqual(res.status_code, 200)
        p = LessonProgress.objects.get(student=self.student, lesson=self.free_lesson)
        self.assertEqual(p.position_seconds, 42)
        self.assertFalse(p.completed)

    def test_marks_complete_and_latches(self):
        self.client.post(self._url(self.free_lesson), {"position": "100", "completed": "1"})
        p = LessonProgress.objects.get(student=self.student, lesson=self.free_lesson)
        self.assertTrue(p.completed)
        # a later ping without completed must not un-complete
        self.client.post(self._url(self.free_lesson), {"position": "10"})
        p.refresh_from_db()
        self.assertTrue(p.completed)

    def test_progress_blocked_for_locked_lesson(self):
        # Basic student cannot save progress on an Advance-gated lesson.
        res = self.client.post(self._url(self.adv_lesson), {"position": "5"})
        self.assertEqual(res.status_code, 404)
        self.assertFalse(LessonProgress.objects.filter(lesson=self.adv_lesson).exists())


class CheckoutTests(BaseData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    @override_settings(UPI_VPA="pay@upi", RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
    def test_checkout_shows_upi(self):
        url = reverse("courses:checkout", args=[self.batch.code]) + f"?plan={self.basic.slug}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        # App deep links + QR (the raw VPA text is intentionally not shown).
        self.assertContains(res, "Pay with GPay")
        self.assertContains(res, "phonepe://pay?")
        self.assertContains(res, "data:image/png;base64,")  # UPI QR
        self.assertContains(res, 'name="screenshot"')  # screenshot upload

    def test_checkout_chooser_lists_plans(self):
        res = self.client.get(reverse("courses:checkout", args=[self.batch.code]))
        self.assertContains(res, "Basic")
        self.assertContains(res, "Advance")

    def test_upi_submit_creates_pending_payment_and_provisional_access(self):
        url = reverse("courses:upi_submit", args=[self.batch.code])
        res = self.client.post(url, {"plan": self.advance.slug, "upi_reference": "UTR123"})
        self.assertEqual(res.status_code, 200)
        pay = Payment.objects.get(student=self.student, batch=self.batch)
        self.assertEqual(pay.status, Payment.Status.PENDING)
        self.assertEqual(pay.upi_reference, "UTR123")
        # Provisional preview access is granted immediately (not full).
        e = BatchEnrollment.objects.get(student=self.student, batch=self.batch)
        self.assertTrue(e.is_active)
        self.assertTrue(e.is_provisional)

    def test_upi_submit_requires_reference_or_screenshot(self):
        url = reverse("courses:upi_submit", args=[self.batch.code])
        res = self.client.post(url, {"plan": self.basic.slug}, follow=True)
        self.assertFalse(Payment.objects.filter(student=self.student).exists())
        self.assertContains(res, "transaction")

    def test_admin_approval_upgrades_provisional_to_full(self):
        # Buy Advance via UPI → provisional preview, then admin marks paid → full.
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.advance, amount=3000,
            method=Payment.Method.MANUAL_UPI, status=Payment.Status.PENDING, upi_reference="U1",
        )
        pay.grant_provisional_access()
        e = BatchEnrollment.objects.get(student=self.student, batch=self.batch)
        self.assertTrue(e.is_provisional)
        pay.mark_paid()
        e.refresh_from_db()
        self.assertFalse(e.is_provisional)
        self.assertEqual(e.plan, self.advance)

    def test_landing_page_for_unenrolled_self_paced(self):
        res = self.client.get(self.batch.get_absolute_url())
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Enroll now")

    def test_catalog_lists_course(self):
        res = self.client.get(reverse("courses:catalog"))
        self.assertContains(res, "Recorded Trading")


@override_settings(
    RAZORPAY_KEY_ID="rzp_test", RAZORPAY_KEY_SECRET="secret", RAZORPAY_ENABLED=True
)
class RazorpayVerifyTests(BaseData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    def test_verify_unlocks_on_valid_signature(self):
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.basic, amount=1000,
            method=Payment.Method.RAZORPAY, razorpay_order_id="order_abc",
        )
        pid = "pay_abc"
        sig = hmac.new(b"secret", f"order_abc|{pid}".encode(), hashlib.sha256).hexdigest()
        url = reverse("courses:razorpay_verify", args=[self.batch.code])
        res = self.client.post(url, {
            "razorpay_order_id": "order_abc",
            "razorpay_payment_id": pid,
            "razorpay_signature": sig,
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.Status.PAID)
        self.assertTrue(BatchEnrollment.objects.filter(student=self.student).exists())

    def test_verify_rejects_bad_signature(self):
        Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.basic, amount=1000,
            method=Payment.Method.RAZORPAY, razorpay_order_id="order_xyz",
        )
        url = reverse("courses:razorpay_verify", args=[self.batch.code])
        res = self.client.post(url, {
            "razorpay_order_id": "order_xyz",
            "razorpay_payment_id": "pay_xyz",
            "razorpay_signature": "wrong",
        })
        self.assertEqual(res.status_code, 400)
        self.assertFalse(BatchEnrollment.objects.filter(student=self.student).exists())


@override_settings(RAZORPAY_WEBHOOK_SECRET="whsec")
class WebhookTests(BaseData):
    def test_webhook_unlocks_on_captured(self):
        pay = Payment.objects.create(
            student=self.student, batch=self.batch, plan=self.advance, amount=3000,
            method=Payment.Method.RAZORPAY, razorpay_order_id="order_hook",
        )
        body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_hook", "order_id": "order_hook"}}},
        }).encode()
        sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        res = self.client.post(
            reverse("courses:razorpay_webhook"), data=body,
            content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sig,
        )
        self.assertEqual(res.status_code, 200)
        pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.Status.PAID)
        self.assertEqual(pay.razorpay_payment_id, "pay_hook")
        self.assertTrue(BatchEnrollment.objects.filter(student=self.student).exists())

    def test_webhook_rejects_bad_signature(self):
        res = self.client.post(
            reverse("courses:razorpay_webhook"), data=b"{}",
            content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="bad",
        )
        self.assertEqual(res.status_code, 400)
