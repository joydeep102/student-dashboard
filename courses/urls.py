from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    path("batch/<slug:code>/", views.batch_detail, name="batch"),
    path("batch/<slug:code>/lesson/<int:pk>/", views.lesson_view, name="lesson"),
    path("batch/<slug:code>/lesson/<int:pk>/source/", views.lesson_source, name="lesson_source"),
]
