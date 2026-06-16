from django.urls import path

from . import views

app_name = "classroom"

urlpatterns = [
    path("live/<int:pk>/join/", views.join_live, name="join_live"),
]
