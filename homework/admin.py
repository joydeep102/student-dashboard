from django.contrib import admin

from .models import HomeTask, HomeworkSubmission, SubmissionImage


class SubmissionImageInline(admin.TabularInline):
    model = SubmissionImage
    extra = 0
    fields = ("image", "verdict", "note")


@admin.register(HomeTask)
class HomeTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "live_class", "plan_labels", "created_by", "created_at", "images_purged")
    list_filter = ("images_purged", "created_at")
    search_fields = ("title", "instructions")
    autocomplete_fields = ["live_class", "created_by"]
    filter_horizontal = ("allowed_plans",)


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "hometask", "overall", "submitted_at", "reviewed_at")
    list_filter = ("overall", "submitted_at")
    search_fields = ("student__email", "hometask__title")
    autocomplete_fields = ["hometask", "student"]
    inlines = [SubmissionImageInline]