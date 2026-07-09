import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Batch,
    BatchEnrollment,
    Course,
    CourseEnrollment,
    CoursePayment,
    Lecture,
    Lesson,
    LessonProgress,
    Payment,
    Plan,
    RecordedCourse,
    Section,
)

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


class PublicCheckoutTests(BaseData):
    """Logged-out visitors (from the marketing site) browse + self-register."""

    def test_catalog_is_public(self):
        res = self.client.get(reverse("courses:catalog"))  # no login
        self.assertEqual(res.status_code, 200)

    def test_landing_is_public(self):
        res = self.client.get(self.batch.get_absolute_url())  # no login
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Enroll now")

    def test_checkout_prompts_registration_when_logged_out(self):
        url = reverse("courses:checkout", args=[self.batch.code]) + f"?plan={self.advance.slug}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Create your account")
        self.assertContains(res, 'name="password"')

    @override_settings(UPI_VPA="pay@upi")
    def test_register_creates_account_and_reaches_payment(self):
        url = reverse("courses:checkout_register", args=[self.batch.code])
        res = self.client.post(url, {
            "plan": self.advance.slug,
            "name": "New Buyer",
            "email": "buyer@test.com",
            "phone": "9998887776",
            "password": "s3curePass!22",
        })
        # Account created with the details, logged in, redirected to checkout.
        u = User.objects.get(email="buyer@test.com")
        self.assertEqual(u.role, "student")
        self.assertEqual(u.phone, "9998887776")
        self.assertEqual(u.first_name, "New")
        self.assertRedirects(
            res,
            reverse("courses:checkout", args=[self.batch.code]) + f"?plan={self.advance.slug}",
        )
        # Following that redirect now shows the payment page (logged in).
        pay_page = self.client.get(res.url)
        self.assertContains(pay_page, "Amount to pay")
        self.assertContains(pay_page, "Pay by UPI")

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(email="dupe@test.com", password="x", role="student")
        url = reverse("courses:checkout_register", args=[self.batch.code])
        res = self.client.post(url, {
            "plan": self.advance.slug, "name": "A", "email": "dupe@test.com",
            "phone": "1", "password": "s3curePass!22",
        })
        self.assertContains(res, "already exists")
        self.assertEqual(User.objects.filter(email="dupe@test.com").count(), 1)

    def test_register_rejects_weak_password(self):
        url = reverse("courses:checkout_register", args=[self.batch.code])
        res = self.client.post(url, {
            "plan": self.advance.slug, "name": "A", "email": "weak@test.com",
            "phone": "1", "password": "123",
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(email="weak@test.com").exists())


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


class RecordedCourseData(TestCase):
    """A published Udemy-style course: 1 preview lecture + 2 paid lectures."""

    def setUp(self):
        self.instructor = User.objects.create_user(
            email="tutor@test.com", password="pw", role="instructor"
        )
        self.course = RecordedCourse.objects.create(
            title="Options Mastery", instructor=self.instructor, price=2999, is_published=True
        )
        self.sec = Section.objects.create(course=self.course, title="Intro", order=1)
        self.lec1 = Lecture.objects.create(
            section=self.sec, title="Welcome", youtube_id="aaaaaaaaaaa", order=1, is_preview=True
        )
        self.lec2 = Lecture.objects.create(
            section=self.sec, title="Setup", youtube_id="bbbbbbbbbbb", order=2
        )
        self.lec3 = Lecture.objects.create(
            section=self.sec, title="Advanced", youtube_id="ccccccccccc", order=3
        )
        self.student = User.objects.create_user(
            email="learn@test.com", password="pw", role="student", phone="9",
        )


class RecordedCourseAccessTests(RecordedCourseData):
    def test_catalog_and_landing_public(self):
        cat = self.client.get(reverse("courses:catalog"))
        self.assertContains(cat, "Options Mastery")
        land = self.client.get(self.course.get_absolute_url())
        self.assertEqual(land.status_code, 200)
        self.assertContains(land, "Welcome")       # preview lecture visible
        self.assertContains(land, "Enroll now")

    def test_preview_lecture_watchable_by_anyone(self):
        # Anonymous can hit the preview lecture source.
        res = self.client.get(
            reverse("courses:lecture_source", args=[self.course.slug, self.lec1.pk])
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["videoId"], "aaaaaaaaaaa")

    def test_paid_lecture_blocked_without_enrollment(self):
        res = self.client.get(
            reverse("courses:lecture_source", args=[self.course.slug, self.lec2.pk])
        )
        self.assertEqual(res.status_code, 404)

    def test_full_enrollment_unlocks_all(self):
        CourseEnrollment.objects.create(student=self.student, course=self.course)
        self.client.force_login(self.student)
        res = self.client.get(reverse("courses:learn", args=[self.course.slug, self.lec3.pk]))
        self.assertEqual(res.status_code, 200)

    @override_settings(PROVISIONAL_PREVIEW_LESSONS=2)
    def test_provisional_previews_first_two_only(self):
        from .access import can_watch_lecture, get_course_enrollment

        CourseEnrollment.objects.create(
            student=self.student, course=self.course, is_provisional=True
        )
        e = get_course_enrollment(self.student, self.course)
        self.assertTrue(can_watch_lecture(self.student, self.lec1, e))   # preview
        self.assertTrue(can_watch_lecture(self.student, self.lec2, e))   # 2nd
        self.assertFalse(can_watch_lecture(self.student, self.lec3, e))  # 3rd locked


class RecordedCoursePaymentTests(RecordedCourseData):
    def test_mark_paid_creates_full_enrollment(self):
        pay = CoursePayment.objects.create(
            student=self.student, course=self.course, amount=2999,
            method=CoursePayment.Method.MANUAL_UPI, status=CoursePayment.Status.PENDING,
        )
        pay.mark_paid()
        e = CourseEnrollment.objects.get(student=self.student, course=self.course)
        self.assertTrue(e.is_active)
        self.assertFalse(e.is_provisional)

    def test_upi_submit_grants_provisional(self):
        self.client.force_login(self.student)
        res = self.client.post(
            reverse("courses:course_upi_submit", args=[self.course.slug]),
            {"upi_reference": "UTR55"},
        )
        self.assertEqual(res.status_code, 200)
        pay = CoursePayment.objects.get(student=self.student, course=self.course)
        self.assertEqual(pay.status, CoursePayment.Status.PENDING)
        e = CourseEnrollment.objects.get(student=self.student, course=self.course)
        self.assertTrue(e.is_provisional)

    @override_settings(RAZORPAY_WEBHOOK_SECRET="whsec")
    def test_course_webhook_unlocks(self):
        pay = CoursePayment.objects.create(
            student=self.student, course=self.course, amount=2999,
            method=CoursePayment.Method.RAZORPAY, razorpay_order_id="order_c1",
        )
        body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_c1", "order_id": "order_c1"}}},
        }).encode()
        sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        res = self.client.post(
            reverse("courses:course_razorpay_webhook"), data=body,
            content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sig,
        )
        self.assertEqual(res.status_code, 200)
        pay.refresh_from_db()
        self.assertEqual(pay.status, CoursePayment.Status.PAID)
        self.assertTrue(CourseEnrollment.objects.filter(student=self.student).exists())


class CourseStudioTests(RecordedCourseData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor)

    def test_instructor_builds_and_publishes_course(self):
        # Create a fresh draft course.
        self.client.post(reverse("trainers:course_create"), {"title": "My New Course"})
        course = RecordedCourse.objects.get(title="My New Course")
        self.assertEqual(course.instructor, self.instructor)
        self.assertFalse(course.is_published)

        # Add a section + lecture.
        self.client.post(reverse("trainers:section_add", args=[course.slug]), {"title": "Ch 1"})
        section = course.sections.get()
        self.client.post(
            reverse("trainers:lecture_add", args=[course.slug, section.pk]),
            {"title": "Lesson A", "youtube_id": "zzzzzzzzzzz", "duration_min": "5"},
        )
        lec = section.lectures.get()
        self.assertEqual(lec.duration_seconds, 300)

        # Publish.
        self.client.post(reverse("trainers:course_publish", args=[course.slug]))
        course.refresh_from_db()
        self.assertTrue(course.is_published)

    def test_sales_tracking(self):
        # One paid + one pending payment for the instructor's course.
        buyer = User.objects.create_user(email="b1@test.com", password="pw", role="student")
        CoursePayment.objects.create(
            student=buyer, course=self.course, amount=2999,
            method=CoursePayment.Method.RAZORPAY, status=CoursePayment.Status.PAID,
        )
        buyer2 = User.objects.create_user(email="b2@test.com", password="pw", role="student")
        CoursePayment.objects.create(
            student=buyer2, course=self.course, amount=2999,
            method=CoursePayment.Method.MANUAL_UPI, status=CoursePayment.Status.PENDING,
        )
        # My Courses shows earnings.
        page = self.client.get(reverse("trainers:courses"))
        self.assertContains(page, "Total earnings")
        self.assertContains(page, "2999")           # revenue from the paid sale
        # Sales detail lists the buyers.
        sales = self.client.get(reverse("trainers:course_sales", args=[self.course.slug]))
        self.assertContains(sales, "b1@test.com")
        self.assertContains(sales, "b2@test.com")
        self.assertContains(sales, "Pending")

    def test_instructor_payout_share_and_payout(self):
        from decimal import Decimal

        from .models import Payout
        from .payment_config import instructor_earnings

        # Two paid sales of ₹2999 each = ₹5998 gross.
        for i in range(2):
            b = User.objects.create_user(email=f"pb{i}@test.com", password="pw", role="student")
            CoursePayment.objects.create(
                student=b, course=self.course, amount=2999,
                method=CoursePayment.Method.RAZORPAY, status=CoursePayment.Status.PAID,
            )
        # Instructor keeps 60%.
        self.instructor.payout_share_percent = 60
        self.instructor.save()
        earn = instructor_earnings(self.instructor)
        self.assertEqual(earn["gross"], Decimal("5998"))
        self.assertEqual(earn["payable"], Decimal("3598.80"))
        self.assertEqual(earn["balance"], Decimal("3598.80"))

        # Admin records a payout via the button.
        admin = User.objects.create_user(
            email="boss@test.com", password="pw", role="admin", is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)
        res = self.client.post(
            reverse("trainers:payout_pay", args=[self.instructor.id]),
            {"amount": "3000", "note": "UPI ref 123"},
        )
        self.assertEqual(Payout.objects.filter(instructor=self.instructor).count(), 1)
        earn = instructor_earnings(self.instructor)
        self.assertEqual(earn["paid_out"], Decimal("3000"))
        self.assertEqual(earn["balance"], Decimal("598.80"))

    def test_instructor_requests_payout_admin_approves(self):
        from decimal import Decimal

        from .models import Payout
        from .payment_config import instructor_earnings

        buyer = User.objects.create_user(email="rq@test.com", password="pw", role="student")
        CoursePayment.objects.create(
            student=buyer, course=self.course, amount=1000,
            method=CoursePayment.Method.RAZORPAY, status=CoursePayment.Status.PAID,
        )
        self.instructor.payout_share_percent = 50
        self.instructor.save()
        # Instructor requests their available ₹500.
        self.client.force_login(self.instructor)
        self.client.post(reverse("trainers:request_payout"), {"amount": "500", "note": "me@upi"})
        req = Payout.objects.get(instructor=self.instructor)
        self.assertEqual(req.status, Payout.Status.REQUESTED)
        earn = instructor_earnings(self.instructor)
        self.assertEqual(earn["requested"], Decimal("500"))
        self.assertEqual(earn["available"], Decimal("0"))   # nothing left to request
        self.assertEqual(earn["balance"], Decimal("500"))   # still owed until paid

        # Instructor can't over-request beyond available.
        self.client.post(reverse("trainers:request_payout"), {"amount": "999"})
        self.assertEqual(Payout.objects.filter(instructor=self.instructor).count(), 1)

        # Admin approves → paid.
        admin = User.objects.create_user(
            email="boss2@test.com", password="pw", role="admin", is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)
        self.client.post(reverse("trainers:payout_approve", args=[req.pk]), {"note": "utr9"})
        req.refresh_from_db()
        self.assertEqual(req.status, Payout.Status.PAID)
        self.assertIsNotNone(req.paid_at)
        earn = instructor_earnings(self.instructor)
        self.assertEqual(earn["paid_out"], Decimal("500"))
        self.assertEqual(earn["balance"], Decimal("0"))

    def test_payouts_page_is_staff_only(self):
        # A plain instructor can't open the admin payouts page.
        res = self.client.get(reverse("trainers:payouts"))
        self.assertNotEqual(res.status_code, 200)  # redirect to admin login

    def test_cannot_edit_another_instructors_course(self):
        other = User.objects.create_user(email="other@test.com", password="pw", role="instructor")
        self.client.force_login(other)
        res = self.client.post(
            reverse("trainers:section_add", args=[self.course.slug]), {"title": "Hack"}
        )
        self.assertEqual(res.status_code, 403)


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
