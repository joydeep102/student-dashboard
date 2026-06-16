from django.conf import settings
from django.db import models

from classroom.models import LiveClass
from courses.models import Plan


class HomeTask(models.Model):
    """A homework assignment tied to a live class. Only students whose plan is in
    ``allowed_plans`` (copied from the class) see it — same gating as the class."""

    live_class = models.ForeignKey(
        LiveClass, on_delete=models.CASCADE, related_name="hometasks"
    )
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="hometasks_created",
    )
    allowed_plans = models.ManyToManyField(Plan, blank=True, related_name="hometasks")
    created_at = models.DateTimeField(auto_now_add=True)
    images_purged = models.BooleanField(
        default=False, help_text="Set once submission images are auto-deleted to save storage."
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def batch(self):
        return self.live_class.batch

    def is_open_to(self, plan):
        if plan is None:
            return False
        ids = set(self.allowed_plans.values_list("id", flat=True))
        return (not ids) or (plan.id in ids)

    @property
    def plan_labels(self):
        names = list(self.allowed_plans.values_list("name", flat=True))
        return ", ".join(names) if names else "Everyone in batch"


class HomeworkSubmission(models.Model):
    class Verdict(models.TextChoices):
        PENDING = "pending", "Pending review"
        CORRECT = "correct", "Correct"
        WRONG = "wrong", "Needs work"

    hometask = models.ForeignKey(
        HomeTask, on_delete=models.CASCADE, related_name="submissions"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="homework_submissions"
    )
    answer_text = models.TextField(blank=True)
    overall = models.CharField(max_length=10, choices=Verdict.choices, default=Verdict.PENDING)
    remarks = models.TextField(blank=True, help_text="Trainer's feedback to the student.")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("hometask", "student")
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.student} · {self.hometask.title}"


class SubmissionImage(models.Model):
    class Verdict(models.TextChoices):
        NONE = "none", "Not marked"
        CORRECT = "correct", "Correct"
        WRONG = "wrong", "Wrong"

    submission = models.ForeignKey(
        HomeworkSubmission, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="homework/%Y/%m/")
    verdict = models.CharField(max_length=10, choices=Verdict.choices, default=Verdict.NONE)
    note = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"image #{self.pk} ({self.verdict})"


def purge_due_homework_images():
    """Delete submission images once 2+ live classes have run in the batch after
    the homework's class — keeps verdicts/remarks, frees image storage.

    Safe to call often (e.g. whenever a new live class is created); it only acts
    on tasks that have crossed the threshold and haven't been purged yet.
    """
    tasks = (
        HomeTask.objects.filter(images_purged=False)
        .select_related("live_class", "live_class__batch")
    )
    for ht in tasks:
        later = (
            LiveClass.objects.filter(
                batch_id=ht.live_class.batch_id,
                start_time__gt=ht.live_class.start_time,
            )
            .exclude(status=LiveClass.Status.CANCELLED)
            .count()
        )
        if later < 2:
            continue
        for img in SubmissionImage.objects.filter(submission__hometask=ht):
            img.image.delete(save=False)
            img.delete()
        ht.images_purged = True
        ht.save(update_fields=["images_purged"])