"""Root URL configuration for the Student Dashboard portal."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

# Brand the Django admin (used by staff to manage students/courses/classes).
admin.site.site_header = "Online Courses — Admin"
admin.site.site_title = "Course Portal Admin"
admin.site.index_title = "Manage students, courses & live classes"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("classroom/", include("classroom.urls")),
    path("trainer/", include("trainers.urls")),
    path("homework/", include("homework.urls")),
    path("", include("courses.urls")),
]

# Serve user-uploaded media through Django in all environments. Static files are
# handled by WhiteNoise (production) or staticfiles (DEBUG). For larger scale,
# put media behind nginx / object storage instead.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
]
