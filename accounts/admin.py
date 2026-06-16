from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from courses.models import BatchEnrollment

User = get_user_model()


class BatchEnrollmentInline(admin.TabularInline):
    """Enroll a student into batches (with a plan) from their user page."""

    model = BatchEnrollment
    fk_name = "student"
    extra = 1
    autocomplete_fields = ["batch", "plan"]
    verbose_name = "Batch enrollment"
    verbose_name_plural = "Batch enrollments (pick a batch and the student's plan)"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "display_name", "role", "is_active", "date_joined")
    list_display_links = ("email", "display_name")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)
    inlines = [BatchEnrollmentInline]

    # Edit form — email is the login; full name + role below.
    fieldsets = (
        ("Login", {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Portal profile", {"fields": ("role", "phone", "avatar", "bio")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Streamlined "Add user" form: email + password + details.
    add_fieldsets = (
        (
            "Account",
            {"classes": ("wide",), "fields": ("email", "password1", "password2")},
        ),
        (
            "User details",
            {"classes": ("wide",), "fields": ("first_name", "last_name", "role", "phone")},
        ),
    )

    def get_changeform_initial_data(self, request):
        # New accounts default to "student" so admins rarely change it.
        return {"role": User.Role.STUDENT}
