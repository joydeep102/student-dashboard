from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class PaymentSettings(models.Model):
    """Site-wide payment configuration, editable from the admin.

    Values entered here override the corresponding environment variables, so an
    admin can turn on UPI (or Razorpay) without touching env / redeploying. Leave
    a field blank to fall back to its environment value.
    """

    upi_vpa = models.CharField(
        "UPI ID (VPA)", max_length=100, blank=True,
        help_text="e.g. yourname@okhdfcbank. Setting this turns on the UPI option.",
    )
    upi_payee_name = models.CharField(max_length=100, blank=True, help_text="Name shown in the UPI app.")
    razorpay_key_id = models.CharField(max_length=60, blank=True)
    razorpay_key_secret = models.CharField(max_length=120, blank=True)
    razorpay_webhook_secret = models.CharField(max_length=120, blank=True)
    preview_lessons = models.PositiveSmallIntegerField(
        default=2,
        help_text="Lectures a manual-UPI buyer can preview before admin verification.",
    )

    class Meta:
        verbose_name = "Payment settings"
        verbose_name_plural = "Payment settings"

    def __str__(self):
        return "Payment settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)


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
    is_self_paced = models.BooleanField(
        default=False,
        help_text="A recorded, on-demand course (no live schedule). Students can "
        "buy in individually and watch at their own pace, Udemy-style.",
    )
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
        help_text="Deprecated — use 'Allowed plans' instead.",
    )
    allowed_plans = models.ManyToManyField(
        Plan,
        blank=True,
        related_name="allowed_slots",
        help_text="Default plans that can join classes on this day. Empty = everyone in the batch.",
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
    is_provisional = models.BooleanField(
        default=False,
        help_text="Manual-UPI payment awaiting admin verification — the student "
        "can preview only the first few lessons until it's approved.",
    )

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


class LessonProgress(models.Model):
    """How far a student has watched a recorded lesson (Udemy-style).

    One row per (student, lesson). ``position_seconds`` is the resume point the
    player seeks back to; ``completed`` flips true once the student has watched
    most of the video (set by the player near the end).
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
        limit_choices_to={"role": "student"},
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    position_seconds = models.PositiveIntegerField(default=0, help_text="Resume point.")
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "lesson")
        ordering = ["-updated_at"]
        verbose_name_plural = "Lesson progress"

    def __str__(self):
        state = "done" if self.completed else f"{self.position_seconds}s"
        return f"{self.student} · {self.lesson.title} · {state}"


class Payment(models.Model):
    """A student's purchase of access to a batch on a specific plan.

    Two routes both end at the same door — ``grant_access`` creates/activates the
    student's :class:`BatchEnrollment`:

    * ``manual_upi`` — student pays to the portal's UPI ID and submits the UTR /
      reference; an admin verifies it and marks the payment paid.
    * ``razorpay`` — online checkout; the success webhook verifies the signature
      and marks the payment paid automatically.
    """

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending verification"  # manual UPI: ref submitted
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    class Method(models.TextChoices):
        MANUAL_UPI = "manual_upi", "Manual UPI"
        RAZORPAY = "razorpay", "Razorpay"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
        limit_choices_to={"role": "student"},
    )
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)

    # Manual UPI: the transaction reference / UTR and/or a payment screenshot the
    # student submits for an admin to verify.
    upi_reference = models.CharField(max_length=60, blank=True)
    screenshot = models.ImageField(upload_to="upi_screenshots/", blank=True, null=True)

    # Razorpay identifiers (blank for manual payments).
    razorpay_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=60, blank=True)
    razorpay_signature = models.CharField(max_length=200, blank=True)

    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} · {self.batch.name} · {self.plan.name} · {self.get_status_display()}"

    def grant_access(self):
        """Create or reactivate the student's FULL enrollment for this plan.

        If the student already has an enrollment in the batch, keep the higher
        of the two plan levels (so a purchase never downgrades an existing tier),
        reactivate it, and clear any provisional (preview-only) flag. Returns the
        enrollment.
        """
        enrollment, created = BatchEnrollment.objects.get_or_create(
            student=self.student,
            batch=self.batch,
            defaults={"plan": self.plan, "is_active": True, "is_provisional": False},
        )
        if not created:
            fields = ["is_active", "is_provisional"]
            if self.plan.level > enrollment.plan.level:
                enrollment.plan = self.plan
                fields.append("plan")
            enrollment.is_active = True
            enrollment.is_provisional = False  # full access now
            enrollment.save(update_fields=fields)
        return enrollment

    def grant_provisional_access(self):
        """Give preview-only access (first few lessons) while a manual-UPI payment
        awaits admin verification. Never touches an existing full enrollment.
        """
        enrollment = BatchEnrollment.objects.filter(
            student=self.student, batch=self.batch
        ).first()
        if enrollment is not None:
            # Already has full access — leave it alone (don't restrict a real tier).
            if enrollment.is_active and not enrollment.is_provisional:
                return enrollment
            fields = ["is_active", "is_provisional"]
            if self.plan.level > enrollment.plan.level:
                enrollment.plan = self.plan
                fields.append("plan")
            enrollment.is_active = True
            enrollment.is_provisional = True
            enrollment.save(update_fields=fields)
            return enrollment
        return BatchEnrollment.objects.create(
            student=self.student,
            batch=self.batch,
            plan=self.plan,
            is_active=True,
            is_provisional=True,
        )

    def mark_paid(self):
        """Mark the payment paid and grant full course access (idempotent)."""
        if self.status != self.Status.PAID:
            self.status = self.Status.PAID
            self.paid_at = timezone.now()
            self.save(update_fields=["status", "paid_at"])
        return self.grant_access()


# ===========================================================================
# Udemy-style recorded courses
#
# A standalone, self-paced video course owned and designed by an instructor —
# bought once for full lifetime access (no cohort/batch, no plan tiers). Content
# is a curriculum of Sections, each holding ordered Lectures.
# ===========================================================================


class RecordedCourse(models.Model):
    """A standalone on-demand video course (Udemy-style)."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subtitle = models.CharField(max_length=300, blank=True, help_text="Short one-line pitch.")
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to="course_thumbs/", blank=True, null=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_courses",
        limit_choices_to={"role__in": ["instructor", "admin"]},
        help_text="The instructor who owns and designs this course.",
    )
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    is_published = models.BooleanField(
        default=False, help_text="Published courses appear in the public catalog."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "course"
            slug, i = base, 2
            while RecordedCourse.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("courses:course", kwargs={"slug": self.slug})

    def ordered_lectures(self):
        """All lectures in curriculum order (section order, then lecture order)."""
        lectures = []
        for section in self.sections.prefetch_related("lectures").all():
            lectures.extend(section.lectures.all())
        return lectures

    @property
    def lecture_count(self):
        return Lecture.objects.filter(section__course=self).count()

    @property
    def total_seconds(self):
        return (
            Lecture.objects.filter(section__course=self).aggregate(
                s=models.Sum("duration_seconds")
            )["s"]
            or 0
        )

    @property
    def duration_display(self):
        secs = self.total_seconds
        if not secs:
            return ""
        m = secs // 60
        h, m = divmod(m, 60)
        return f"{h}h {m}m" if h else f"{m}m"


class Section(models.Model):
    """A curriculum section/chapter grouping lectures within a course."""

    course = models.ForeignKey(RecordedCourse, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.course.title} — {self.title}"


class Lecture(models.Model):
    """A single video lecture inside a section.

    Video is an *unlisted* YouTube id played through the branded in-portal
    player. ``is_preview`` lectures are free to watch for anyone (the Udemy
    "preview" sample); all others need an active enrollment.
    """

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="lectures")
    title = models.CharField(max_length=200)
    youtube_id = models.CharField(
        max_length=20,
        help_text="The 11-character YouTube video id of the UNLISTED upload.",
    )
    duration_seconds = models.PositiveIntegerField(default=0, help_text="Optional, for display.")
    is_preview = models.BooleanField(
        default=False, help_text="Free preview — anyone can watch without buying."
    )
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.section.title} — {self.title}"

    @property
    def course(self):
        return self.section.course

    def get_absolute_url(self):
        return reverse(
            "courses:learn", kwargs={"slug": self.section.course.slug, "pk": self.pk}
        )

    @property
    def duration_display(self):
        if not self.duration_seconds:
            return ""
        m, s = divmod(self.duration_seconds, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class CourseEnrollment(models.Model):
    """A student's purchased access to a recorded course (full, lifetime)."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_enrollments",
        limit_choices_to={"role": "student"},
    )
    course = models.ForeignKey(RecordedCourse, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_provisional = models.BooleanField(
        default=False,
        help_text="Manual-UPI payment awaiting verification — preview access only.",
    )

    class Meta:
        unique_together = ("student", "course")
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.student} · {self.course.title}"


class LectureProgress(models.Model):
    """How far a student has watched a lecture (resume + completion)."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lecture_progress",
        limit_choices_to={"role": "student"},
    )
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="progress")
    position_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "lecture")
        ordering = ["-updated_at"]
        verbose_name_plural = "Lecture progress"

    def __str__(self):
        state = "done" if self.completed else f"{self.position_seconds}s"
        return f"{self.student} · {self.lecture.title} · {state}"


class CoursePayment(models.Model):
    """A student's purchase of a recorded course (manual UPI or Razorpay).

    Both routes end at ``grant_access`` which creates/activates the student's
    :class:`CourseEnrollment`.
    """

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending verification"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    class Method(models.TextChoices):
        MANUAL_UPI = "manual_upi", "Manual UPI"
        RAZORPAY = "razorpay", "Razorpay"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_payments",
        limit_choices_to={"role": "student"},
    )
    course = models.ForeignKey(RecordedCourse, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)

    upi_reference = models.CharField(max_length=60, blank=True)
    screenshot = models.ImageField(upload_to="upi_screenshots/", blank=True, null=True)

    razorpay_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=60, blank=True)
    razorpay_signature = models.CharField(max_length=200, blank=True)

    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} · {self.course.title} · {self.get_status_display()}"

    def grant_access(self):
        """Create or activate the student's FULL enrollment (clears provisional)."""
        enrollment, created = CourseEnrollment.objects.get_or_create(
            student=self.student,
            course=self.course,
            defaults={"is_active": True, "is_provisional": False},
        )
        if not created and (not enrollment.is_active or enrollment.is_provisional):
            enrollment.is_active = True
            enrollment.is_provisional = False
            enrollment.save(update_fields=["is_active", "is_provisional"])
        return enrollment

    def grant_provisional_access(self):
        """Give preview-only access while a manual-UPI payment awaits verification."""
        enrollment, created = CourseEnrollment.objects.get_or_create(
            student=self.student,
            course=self.course,
            defaults={"is_active": True, "is_provisional": True},
        )
        # Never downgrade an already-full enrollment.
        return enrollment

    def mark_paid(self):
        """Mark paid and grant full course access (idempotent)."""
        if self.status != self.Status.PAID:
            self.status = self.Status.PAID
            self.paid_at = timezone.now()
            self.save(update_fields=["status", "paid_at"])
        return self.grant_access()
