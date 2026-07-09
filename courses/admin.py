from django.contrib import admin, messages
from django.utils.html import format_html

from classroom.models import LiveClass

from .models import (
    Batch,
    BatchEnrollment,
    BatchScheduleSlot,
    Course,
    CourseEnrollment,
    CoursePayment,
    Lecture,
    LectureProgress,
    Lesson,
    LessonProgress,
    Payment,
    PaymentSettings,
    Payout,
    Plan,
    RecordedCourse,
    Section,
)


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    """Singleton: enter a UPI ID (and/or Razorpay keys) to turn on payments."""

    fieldsets = (
        ("UPI (manual)", {
            "fields": ("upi_vpa", "upi_payee_name"),
            "description": "Enter your UPI ID to switch on the UPI payment option "
            "immediately — no redeploy needed.",
        }),
        ("Razorpay (online)", {
            "fields": ("razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret"),
            "description": "Fill both key id + secret to enable online checkout.",
        }),
        ("Preview & payouts", {"fields": ("preview_lessons", "default_instructor_share")}),
    )

    def has_add_permission(self, request):
        # Singleton — only one row.
        return not PaymentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "price", "duration_months", "badge", "is_active")
    list_editable = ("level", "price", "is_active")
    ordering = ("level",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {"fields": ("name", "slug", "level", "is_active")}),
        ("Pricing", {"fields": ("price", "duration_months")}),
        ("Pricing page look", {"fields": ("badge", "is_highlighted", "accent", "features")}),
    )


class BatchEnrollmentInline(admin.TabularInline):
    model = BatchEnrollment
    extra = 1
    autocomplete_fields = ["student", "plan"]
    verbose_name = "Student in this batch"
    verbose_name_plural = "Students in this batch (set each one's plan)"


class ScheduleSlotInline(admin.TabularInline):
    model = BatchScheduleSlot
    extra = 1
    fields = ("weekday", "start_time", "duration_minutes", "allowed_plans")
    autocomplete_fields = ["allowed_plans"]
    verbose_name = "Weekly class day"
    verbose_name_plural = "Weekly class days (which day each week the batch runs live)"


class LessonInline(admin.StackedInline):
    model = Lesson
    extra = 1
    fields = ("title", "youtube_id", "required_plan", "order", "duration_seconds", "description")
    autocomplete_fields = ["required_plan"]


class LiveClassInline(admin.TabularInline):
    model = LiveClass
    extra = 0
    fields = ("title", "start_time", "duration_minutes", "allowed_plans", "status", "meet_link")
    autocomplete_fields = ["allowed_plans"]
    show_change_link = True


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "is_published", "created_at")
    list_filter = ("is_published",)
    search_fields = ("title", "summary", "description")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ["instructor"]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "trainer", "student_count", "schedule_summary", "is_active")
    list_filter = ("is_active", "is_self_paced", "course", "instructor")
    search_fields = ("name", "code", "course__title")
    prepopulated_fields = {"code": ("name",)}
    autocomplete_fields = ["course", "instructor"]
    fieldsets = (
        (None, {"fields": ("course", "name", "code", "instructor", "is_active")}),
        (
            "Format",
            {
                "fields": ("is_self_paced",),
                "description": "Tick for a recorded, on-demand course (no live "
                "schedule) students can buy into individually.",
            },
        ),
        ("Schedule", {"fields": ("start_date", "end_date")}),
        ("About", {"fields": ("description",)}),
    )
    inlines = [ScheduleSlotInline, BatchEnrollmentInline, LessonInline, LiveClassInline]

    @admin.display(description="Trainer")
    def trainer(self, obj):
        return obj.trainer or "—"


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "batch", "required_plan", "order", "duration_display")
    list_filter = ("batch", "required_plan")
    search_fields = ("title", "description")
    list_editable = ("order",)
    autocomplete_fields = ["batch", "required_plan"]


@admin.register(BatchEnrollment)
class BatchEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "batch", "plan", "enrolled_at", "is_active", "is_provisional")
    list_filter = ("batch", "plan", "is_active", "is_provisional")
    search_fields = ("student__email", "student__first_name", "student__last_name", "batch__name")
    autocomplete_fields = ["student", "batch", "plan"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "student", "student_phone", "student_email", "batch", "plan", "amount",
        "method", "status", "has_proof", "created_at", "paid_at",
    )
    list_filter = ("status", "method", "batch", "plan")
    search_fields = (
        "student__email",
        "student__first_name",
        "student__last_name",
        "student__phone",
        "upi_reference",
        "razorpay_order_id",
        "razorpay_payment_id",
    )
    autocomplete_fields = ["student", "batch", "plan"]
    readonly_fields = (
        "student_phone", "student_email", "screenshot_preview", "created_at",
        "paid_at", "razorpay_order_id", "razorpay_payment_id", "razorpay_signature",
    )
    date_hierarchy = "created_at"
    actions = ["mark_paid_and_enroll"]
    fieldsets = (
        (None, {"fields": ("student", "student_phone", "student_email", "batch", "plan", "amount")}),
        ("Status", {"fields": ("method", "status", "created_at", "paid_at")}),
        ("Manual UPI proof", {"fields": ("upi_reference", "screenshot", "screenshot_preview")}),
        ("Razorpay", {"fields": ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")}),
        ("Notes", {"fields": ("note",)}),
    )

    @admin.display(description="Phone")
    def student_phone(self, obj):
        return obj.student.phone or "—"

    @admin.display(description="Email")
    def student_email(self, obj):
        return obj.student.email

    @admin.display(description="Proof", boolean=True)
    def has_proof(self, obj):
        return bool(obj.screenshot or obj.upi_reference)

    @admin.display(description="Screenshot")
    def screenshot_preview(self, obj):
        if obj.screenshot:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" '
                'style="max-width:340px; border-radius:8px;"></a>',
                obj.screenshot.url,
            )
        return "—"

    @admin.action(description="✓ Mark selected payments PAID and grant FULL course access")
    def mark_paid_and_enroll(self, request, queryset):
        """Verify a manual UPI payment: flip it to paid and give full access
        (upgrading the student from provisional preview to the full course)."""
        done = 0
        for payment in queryset:
            payment.mark_paid()
            done += 1
        self.message_user(
            request,
            f"{done} payment(s) marked paid — students now have full access to their course.",
            messages.SUCCESS,
        )


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("student", "lesson", "position_seconds", "completed", "updated_at")
    list_filter = ("completed", "lesson__batch")
    search_fields = ("student__email", "lesson__title")
    autocomplete_fields = ["student", "lesson"]
    readonly_fields = ("updated_at",)


# ---------------------------------------------------------------------------
# Udemy-style recorded courses
# ---------------------------------------------------------------------------
class SectionInline(admin.TabularInline):
    model = Section
    extra = 1
    fields = ("title", "order")


class LectureInline(admin.StackedInline):
    model = Lecture
    extra = 1
    fields = ("title", "youtube_id", "duration_seconds", "is_preview", "order", "description")


@admin.register(RecordedCourse)
class RecordedCourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "price", "lecture_count", "is_published", "updated_at")
    list_filter = ("is_published", "instructor")
    search_fields = ("title", "subtitle", "description")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ["instructor"]
    inlines = [SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order")
    list_filter = ("course",)
    search_fields = ("title", "course__title")
    inlines = [LectureInline]


@admin.register(Lecture)
class LectureAdmin(admin.ModelAdmin):
    list_display = ("title", "section", "is_preview", "order", "duration_display")
    list_filter = ("is_preview", "section__course")
    search_fields = ("title", "section__title", "section__course__title")


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "enrolled_at", "is_active", "is_provisional")
    list_filter = ("is_active", "is_provisional", "course")
    search_fields = ("student__email", "student__first_name", "student__last_name", "course__title")
    autocomplete_fields = ["student", "course"]


@admin.register(LectureProgress)
class LectureProgressAdmin(admin.ModelAdmin):
    list_display = ("student", "lecture", "position_seconds", "completed", "updated_at")
    list_filter = ("completed", "lecture__section__course")
    search_fields = ("student__email", "lecture__title")
    autocomplete_fields = ["student", "lecture"]
    readonly_fields = ("updated_at",)


@admin.register(CoursePayment)
class CoursePaymentAdmin(admin.ModelAdmin):
    list_display = (
        "student", "student_phone", "student_email", "course", "amount",
        "method", "status", "has_proof", "created_at", "paid_at",
    )
    list_filter = ("status", "method", "course")
    search_fields = (
        "student__email", "student__first_name", "student__last_name",
        "student__phone", "upi_reference", "razorpay_order_id", "razorpay_payment_id",
    )
    autocomplete_fields = ["student", "course"]
    readonly_fields = (
        "student_phone", "student_email", "screenshot_preview", "created_at",
        "paid_at", "razorpay_order_id", "razorpay_payment_id", "razorpay_signature",
    )
    date_hierarchy = "created_at"
    actions = ["mark_paid_and_enroll"]
    fieldsets = (
        (None, {"fields": ("student", "student_phone", "student_email", "course", "amount")}),
        ("Status", {"fields": ("method", "status", "created_at", "paid_at")}),
        ("Manual UPI proof", {"fields": ("upi_reference", "screenshot", "screenshot_preview")}),
        ("Razorpay", {"fields": ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")}),
        ("Notes", {"fields": ("note",)}),
    )

    @admin.display(description="Phone")
    def student_phone(self, obj):
        return obj.student.phone or "—"

    @admin.display(description="Email")
    def student_email(self, obj):
        return obj.student.email

    @admin.display(description="Proof", boolean=True)
    def has_proof(self, obj):
        return bool(obj.screenshot or obj.upi_reference)

    @admin.display(description="Screenshot")
    def screenshot_preview(self, obj):
        if obj.screenshot:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" '
                'style="max-width:340px; border-radius:8px;"></a>',
                obj.screenshot.url,
            )
        return "—"

    @admin.action(description="✓ Mark selected payments PAID and grant FULL course access")
    def mark_paid_and_enroll(self, request, queryset):
        done = 0
        for payment in queryset:
            payment.mark_paid()
            done += 1
        self.message_user(
            request,
            f"{done} payment(s) marked paid — students now have full course access.",
            messages.SUCCESS,
        )


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("instructor", "amount", "status", "note", "created_at", "paid_at", "created_by")
    list_filter = ("status", "instructor")
    search_fields = ("instructor__email", "instructor__first_name", "note")
    autocomplete_fields = ["instructor"]
    readonly_fields = ("created_at",)
    actions = ["approve_payouts"]

    @admin.action(description="✓ Approve & mark selected requests PAID")
    def approve_payouts(self, request, queryset):
        done = 0
        for payout in queryset.filter(status=Payout.Status.REQUESTED):
            payout.mark_paid()
            done += 1
        self.message_user(request, f"{done} payout(s) approved and marked paid.", messages.SUCCESS)
