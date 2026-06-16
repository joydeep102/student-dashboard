from django.urls import path

from . import views

app_name = "trainers"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload, name="upload"),
    path("live/", views.live, name="live"),
    path("live/start/<int:slot_id>/", views.start_live, name="start_live"),
    path("live/end/<int:pk>/", views.end_live, name="end_live"),
]
