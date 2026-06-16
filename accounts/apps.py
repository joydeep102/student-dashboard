from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Inject dashboard stats into the admin home page's context. Done by
        # wrapping the default admin index so we don't depend on a custom
        # template-tag library (which only registers on a full process start).
        from django.contrib import admin

        original_index = admin.site.index

        def index_with_dashboard(request, extra_context=None):
            from django.contrib.auth import get_user_model
            from django.utils import timezone

            from classroom.models import LiveClass
            from courses.models import Batch, BatchEnrollment, Lesson
            from trainers.models import VideoSubmission

            User = get_user_model()
            now = timezone.now()

            extra_context = extra_context or {}
            extra_context["fb_stats"] = {
                "students": User.objects.filter(role=User.Role.STUDENT).count(),
                "batches": Batch.objects.filter(is_active=True).count(),
                "lessons": Lesson.objects.count(),
                "enrollments": BatchEnrollment.objects.filter(is_active=True).count(),
                "live_upcoming": LiveClass.objects.filter(start_time__gte=now)
                .exclude(status=LiveClass.Status.CANCELLED)
                .count(),
                "pending_videos": VideoSubmission.objects.filter(
                    status=VideoSubmission.Status.PENDING
                ).count(),
            }
            extra_context["fb_pending_videos"] = (
                VideoSubmission.objects.filter(status=VideoSubmission.Status.PENDING)
                .select_related("trainer", "batch")
                .order_by("created_at")[:6]
            )
            extra_context["fb_upcoming"] = (
                LiveClass.objects.filter(start_time__gte=now)
                .exclude(status=LiveClass.Status.CANCELLED)
                .select_related("batch")
                .order_by("start_time")[:6]
            )
            extra_context["fb_students"] = User.objects.filter(
                role=User.Role.STUDENT
            ).order_by("-date_joined")[:6]

            from classroom.google_meet import is_configured as calendar_connected
            from trainers.youtube import is_configured as youtube_connected

            extra_context["fb_google"] = {
                "calendar": calendar_connected(),
                "youtube": youtube_connected(),
            }
            return original_index(request, extra_context)

        admin.site.index = index_with_dashboard
