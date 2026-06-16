from django.contrib import admin

from classroom.models import LiveClass

from .models import Batch, BatchEnrollment, BatchScheduleSlot, Course, Lesson, Plan


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
    autocomplete_fields = ["required_plan"]
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
    fields = ("title", "start_time", "duration_minutes", "required_plan", "status", "meet_link")
    autocomplete_fields = ["required_plan"]
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
    list_display = ("name", "course", "student_count", "schedule_summary", "is_active")
    list_filter = ("is_active", "course")
    search_fields = ("name", "code", "course__title")
    prepopulated_fields = {"code": ("name",)}
    autocomplete_fields = ["course"]
    inlines = [ScheduleSlotInline, BatchEnrollmentInline, LessonInline, LiveClassInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "batch", "required_plan", "order", "duration_display")
    list_filter = ("batch", "required_plan")
    search_fields = ("title", "description")
    list_editable = ("order",)
    autocomplete_fields = ["batch", "required_plan"]


@admin.register(BatchEnrollment)
class BatchEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "batch", "plan", "enrolled_at", "is_active")
    list_filter = ("batch", "plan", "is_active")
    search_fields = ("student__email", "student__first_name", "student__last_name", "batch__name")
    autocomplete_fields = ["student", "batch", "plan"]
