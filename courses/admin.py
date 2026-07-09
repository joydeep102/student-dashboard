from django.contrib import admin, messages
from django.utils.html import format_html

from classroom.models import LiveClass

from .models import (
    Batch,
    BatchEnrollment,
    BatchScheduleSlot,
    Course,
    Lesson,
    LessonProgress,
    Payment,
    Plan,
)


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
