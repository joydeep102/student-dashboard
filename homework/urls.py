from django.urls import path

from . import views

app_name = "homework"

urlpatterns = [
    # Student
    path("", views.student_list, name="student_list"),
    path("submit/<int:pk>/", views.submit, name="submit"),
    # Trainer
    path("trainer/", views.trainer_list, name="trainer_list"),
    path("trainer/give/<int:class_pk>/", views.give, name="give"),
    path("trainer/task/<int:pk>/", views.submissions, name="submissions"),
    path("trainer/review/<int:pk>/", views.review, name="review"),
]