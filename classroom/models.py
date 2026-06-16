from django.db import models
from django.utils import timezone

from courses.models import Batch, Plan


class LiveClass(models.Model):
    """A scheduled live session (Google Meet) inside a batch.

    ``required_plan`` gates who can join: a student needs a plan whose level is
    ≥ the class's required plan level. Blank = everyone in the batch can join.
    This is what makes a lower-plan student's classes "end" while upgraded
    students continue into the higher-tier sessions.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        LIVE = "live", "Live now"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="live_classes")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    required_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gated_classes",
        help_text="Minimum plan to join this class. Leave blank so every "
        "student in the batch can join.",
    )

    # Google Meet / Calendar fields (populated automatically).
    meet_link = models.URLField(
        blank=True,
        help_text="Auto-filled from Google Meet. You may also paste a link manually.",
    )
    google_event_id = models.CharField(max_length=255, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time"]
        verbose_name_plural = "Live classes"

    def __str__(self):
        return f"{self.title} ({self.start_time:%d %b %Y, %H:%M})"

    @property
    def required_level(self):
        return self.required_plan.level if self.required_plan_id else 0

    @property
    def end_time(self):
        return self.start_time + timezone.timedelta(minutes=self.duration_minutes)

    @property
    def is_upcoming(self):
        return self.status == self.Status.SCHEDULED and self.start_time > timezone.now()

    @property
    def is_joinable(self):
        """Joinable from 10 minutes before start until the scheduled end."""
        if self.status == self.Status.CANCELLED:
            return False
        now = timezone.now()
        return (self.start_time - timezone.timedelta(minutes=10)) <= now <= self.end_time

    @property
    def live_state(self):
        """Computed display state independent of the stored status field."""
        now = timezone.now()
        if self.status == self.Status.CANCELLED:
            return "cancelled"
        if now < self.start_time - timezone.timedelta(minutes=10):
            return "upcoming"
        if now <= self.end_time:
            return "live"
        return "ended"
