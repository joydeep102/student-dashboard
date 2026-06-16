from django.conf import settings
from django.db import models

from courses.models import Batch, Lesson, Plan


class VideoSubmission(models.Model):
    """A video a trainer uploads for review.

    Flow:  pending  ->  (admin) approve  ->  uploaded to YouTube (unlisted)
                                          ->  a Lesson is created in the batch
           pending  ->  (admin) reject
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved & uploaded"
        REJECTED = "rejected", "Rejected"

    class Upload(models.TextChoices):
        NONE = "none", "Not uploaded"
        UPLOADING = "uploading", "Uploading…"
        DONE = "done", "Uploaded to YouTube"
        FAILED = "failed", "Upload failed"

    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_submissions",
        limit_choices_to={"role__in": ["instructor", "admin"]},
    )
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="video_submissions")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_file = models.FileField(upload_to="trainer_uploads/%Y/%m/")
    required_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Minimum plan to watch once published. Blank = everyone in the batch.",
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    upload_state = models.CharField(max_length=12, choices=Upload.choices, default=Upload.NONE)
    youtube_id = models.CharField(max_length=20, blank=True)
    error = models.TextField(blank=True, editable=False)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_submissions",
    )
    review_notes = models.TextField(blank=True, help_text="Shown to the trainer (e.g. why rejected).")
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.trainer} ({self.get_status_display()})"

    @property
    def youtube_url(self):
        return f"https://youtu.be/{self.youtube_id}" if self.youtube_id else ""
