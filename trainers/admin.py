from django.contrib import admin
from django.db.models import Max
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from courses.models import Lesson

from .models import VideoSubmission
from .youtube import YouTubeUnavailable, is_configured, upload_video


@admin.register(VideoSubmission)
class VideoSubmissionAdmin(admin.ModelAdmin):
    list_display = ("title", "trainer", "batch", "status_badge", "upload_badge", "created_at")
    list_filter = ("status", "upload_state", "batch")
    search_fields = ("title", "description", "trainer__email")
    autocomplete_fields = ["batch", "required_plan", "trainer"]
    readonly_fields = ("trainer", "created_at", "reviewed_at", "reviewed_by", "error",
                       "video_preview", "lesson", "upload_state")
    actions = ["approve_and_publish", "reject_selected"]
    fieldsets = (
        (None, {"fields": ("trainer", "batch", "title", "description", "required_plan")}),
        ("Video file", {"fields": ("video_file", "video_preview")}),
        (
            "Review & publish",
            {
                "fields": ("status", "review_notes", "youtube_id", "upload_state", "lesson", "error"),
                "description": "Use the 'Approve & publish to YouTube' action to upload the file "
                "and publish it to the batch. Or paste a YouTube ID and approve to publish without uploading.",
            },
        ),
        ("Audit", {"fields": ("reviewed_by", "reviewed_at", "created_at")}),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"pending": "#b45309", "approved": "#16a34a", "rejected": "#dc2626"}
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, "#555"), obj.get_status_display()
        )

    @admin.display(description="YouTube")
    def upload_badge(self, obj):
        if obj.youtube_id:
            return format_html('<a href="https://youtu.be/{}" target="_blank">▶ {}</a>',
                               obj.youtube_id, obj.youtube_id)
        return obj.get_upload_state_display()

    @admin.display(description="Preview")
    def video_preview(self, obj):
        if obj.video_file:
            return format_html(
                '<video src="{}" controls style="max-width:420px;border-radius:8px"></video>',
                obj.video_file.url,
            )
        return mark_safe("<em>No file</em>")

    def _publish(self, request, sub):
        """Upload to YouTube (if needed) and create the batch Lesson."""
        yid = sub.youtube_id
        if not yid:
            if not is_configured():
                raise YouTubeUnavailable(
                    "YouTube isn't authorized. Run `python manage.py youtube_auth`, "
                    "or paste a YouTube ID into the submission and approve again."
                )
            sub.upload_state = VideoSubmission.Upload.UPLOADING
            sub.save(update_fields=["upload_state"])
            yid = upload_video(sub.video_file.path, sub.title, sub.description)

        order = (sub.batch.lessons.aggregate(m=Max("order"))["m"] or 0) + 1
        lesson = Lesson.objects.create(
            batch=sub.batch, title=sub.title, description=sub.description,
            youtube_id=yid, required_plan=sub.required_plan, order=order,
        )
        sub.youtube_id = yid
        sub.lesson = lesson
        sub.status = VideoSubmission.Status.APPROVED
        sub.upload_state = VideoSubmission.Upload.DONE
        sub.error = ""
        sub.reviewed_by = request.user
        sub.reviewed_at = timezone.now()
        sub.save()

    @admin.action(description="✅ Approve & publish to YouTube")
    def approve_and_publish(self, request, queryset):
        ok = fail = 0
        for sub in queryset.exclude(status=VideoSubmission.Status.APPROVED):
            try:
                self._publish(request, sub)
                ok += 1
            except Exception as exc:  # noqa: BLE001 - surface any failure to the admin
                sub.upload_state = VideoSubmission.Upload.FAILED
                sub.error = str(exc)
                sub.save(update_fields=["upload_state", "error"])
                fail += 1
                self.message_user(request, f"'{sub.title}': {exc}", level="error")
        if ok:
            self.message_user(request, f"{ok} video(s) published to their batches.")
        elif not fail:
            self.message_user(request, "Nothing to do (already approved).")

    @admin.action(description="🚫 Reject selected")
    def reject_selected(self, request, queryset):
        n = queryset.update(
            status=VideoSubmission.Status.REJECTED, reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{n} submission(s) rejected.")
