from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Plan(models.Model):
    """A pricing tier.

    ``level`` is the access rank — a student can open any content whose required
    plan level is less than or equal to their own plan's level. So Basic (1)
    sees only level-1 content, while Elite (4) sees everything.
    """

    ACCENT_CHOICES = [
        ("green", "Green"),
        ("dark", "Dark"),
        ("gold", "Gold"),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    level = models.PositiveSmallIntegerField(
        unique=True,
        help_text="Access rank. 1 = lowest. Students can open content whose "
        "required level is ≤ their plan level.",
    )
    duration_months = models.PositiveSmallIntegerField(default=3)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    badge = models.CharField(
        max_length=30, blank=True, help_text="Optional ribbon, e.g. 'MOST POPULAR' or 'ELITE'."
    )
    is_highlighted = models.BooleanField(
        default=False, help_text="Visually emphasise this card on the pricing page."
    )
    accent = models.CharField(max_length=10, choices=ACCENT_CHOICES, default="green")
    features = models.TextField(
        blank=True, help_text="One feature per line — shown on the pricing page."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["level"]

    def __str__(self):
        return f"{self.name} (L{self.level})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) or f"plan-{self.level}"
        super().save(*args, **kwargs)

    @property
    def feature_list(self):
        return [ln.strip() for ln in self.features.splitlines() if ln.strip()]


class Course(models.Model):
    """A program (e.g. the trading course) that is delivered batch by batch."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.CharField(max_length=300, blank=True, help_text="Short one-line description.")
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to="course_thumbs/", blank=True, null=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses_taught",
        limit_choices_to={"role__in": ["instructor", "admin"]},
    )
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "course"
            slug = base
            i = 2
            while Course.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Batch(models.Model):
    """A cohort of students running through a course together.

    A batch holds students on different plans. Content (live classes and video
    lessons) inside the batch is gated by plan level, so lower-plan students
    stop getting access once the batch moves into higher-tier material.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="batches")
    name = models.CharField(max_length=100, help_text="e.g. 'Batch 01'")
    code = models.SlugField(max_length=60, unique=True, blank=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches_taught",
        limit_choices_to={"role__in": ["instructor", "admin"]},
        help_text="Trainer who conducts this batch. Leave blank to use the course instructor.",
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "name"]
        verbose_name_plural = "Batches"

    def __str__(self):
        return f"{self.name} · {self.course.title}"

    def save(self, *args, **kwargs):
        if not self.code:
            base = slugify(f"{self.course.title}-{self.name}") or "batch"
            code = base
            i = 2
            while Batch.objects.filter(code=code).exclude(pk=self.pk).exists():
                code = f"{base}-{i}"
                i += 1
            self.code = code
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("courses:batch", kwargs={"code": self.code})

    @property
    def trainer(self):
        """The batch's trainer: its own instructor, else the course instructor."""
        return self.instructor or (self.course.instructor if self.course_id else None)

    @property
    def student_count(self):
        return self.enrollments.filter(is_active=True).count()

    @property
    def schedule_summary(self):
        """Human-readable weekly schedule, e.g. 'Mon 7:00 PM · Wed 7:00 PM'."""
        parts = []
        for s in self.schedule_slots.all():
            t = s.start_time.strftime("%I:%M %p").lstrip("0")
            parts.append(f"{s.get_weekday_display()[:3]} {t}")
        return " · ".join(parts)


class BatchScheduleSlot(models.Model):
    """A recurring weekly time when a batch holds a live class.

    Set by the admin. Trainers may start a live class only on these weekdays.
    """

    class Weekday(models.IntegerChoices):
        MON = 0, "Monday"
        TUE = 1, "Tuesday"
        WED = 2, "Wednesday"
        THU = 3, "Thursday"
        FRI = 4, "Friday"
        SAT = 5, "Saturday"
        SUN = 6, "Sunday"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="schedule_slots")
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField(help_text="Local time the class starts on this day.")
    duration_minutes = models.PositiveIntegerField(default=60)
    required_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Minimum plan to join classes on this day. Blank = everyone in the batch.",
    )

    class Meta:
        ordering = ["weekday", "start_time"]
        unique_together = ("batch", "weekday", "start_time")

    def __str__(self):
        t = self.start_time.strftime("%I:%M %p").lstrip("0")
        return f"{self.batch.name} — {self.get_weekday_display()} {t}"

    @property
    def time_display(self):
        return self.start_time.strftime("%I:%M %p").lstrip("0")


class BatchEnrollment(models.Model):
    """Places a student into a batch on a specific plan (their access tier)."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="batch_enrollments",
        limit_choices_to={"role": "student"},
    )
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="enrollments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("student", "batch")
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.student} · {self.batch.name} · {self.plan.name}"

    @property
    def plan_level(self):
        return self.plan.level


class Lesson(models.Model):
    """A recorded video lesson inside a batch.

    Stored as an *unlisted* YouTube ID and played through the branded in-portal
    player. ``required_plan`` gates who may watch: a student needs a plan whose
    level is ≥ the lesson's required plan level. Blank = everyone in the batch.
    """

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    youtube_id = models.CharField(
        max_length=20,
        help_text="The 11-character YouTube video ID of the UNLISTED upload "
        "(the part after v= or youtu.be/), not the full URL.",
    )
    duration_seconds = models.PositiveIntegerField(default=0, help_text="Optional, for display.")
    order = models.PositiveIntegerField(default=0)
    required_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gated_lessons",
        help_text="Minimum plan to watch this video. Leave blank so every "
        "student in the batch can watch it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["batch", "order", "id"]

    def __str__(self):
        return f"{self.batch.name} — {self.title}"

    def get_absolute_url(self):
        return reverse("courses:lesson", kwargs={"code": self.batch.code, "pk": self.pk})

    @property
    def required_level(self):
        return self.required_plan.level if self.required_plan_id else 0

    @property
    def duration_display(self):
        if not self.duration_seconds:
            return ""
        m, s = divmod(self.duration_seconds, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
