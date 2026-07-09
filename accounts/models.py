from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    """User manager keyed on **email** (the login field) instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        username = extra_fields.pop("username", "") or email
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user that logs in with **email**.

    Accounts are created by staff (admin) only — there is no public signup.
    ``role`` distinguishes portal students from staff/instructors.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        INSTRUCTOR = "instructor", "Instructor"
        STUDENT = "student", "Student"

    # Email is the unique login identifier.
    email = models.EmailField("email address", unique=True)
    # Username kept for display/back-compat only — optional, not the login.
    username = models.CharField(max_length=150, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio = models.TextField(blank=True)
    # Instructor revenue share (% they keep of their course sales). Blank = use
    # the platform default from Payment settings.
    payout_share_percent = models.PositiveSmallIntegerField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email + password are prompted by createsuperuser

    objects = UserManager()

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    def __str__(self):
        full = self.get_full_name()
        return f"{full} ({self.email})" if full else self.email

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def display_name(self):
        return self.get_full_name() or self.email
