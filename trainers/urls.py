from django.urls import path

from . import course_studio, views

app_name = "trainers"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload, name="upload"),
    path("live/", views.live, name="live"),
    path("live/start/<int:slot_id>/", views.start_live, name="start_live"),
    path("live/schedule/<int:slot_id>/", views.schedule_live, name="schedule_live"),
    path("live/end/<int:pk>/", views.end_live, name="end_live"),
    # Course Studio — build recorded courses
    path("courses/", course_studio.my_courses, name="courses"),
    path("courses/new/", course_studio.course_create, name="course_create"),
    # Payouts
    path("payouts/request/", course_studio.request_payout, name="request_payout"),
    path("payouts/", course_studio.payouts, name="payouts"),
    path("payouts/pay/<int:user_id>/", course_studio.payout_pay, name="payout_pay"),
    path("payouts/<int:pk>/approve/", course_studio.payout_approve, name="payout_approve"),
    path("payouts/<int:pk>/reject/", course_studio.payout_reject, name="payout_reject"),
    path("courses/<slug:slug>/sales/", course_studio.course_sales, name="course_sales"),
    path("courses/<slug:slug>/", course_studio.course_edit, name="course_edit"),
    path("courses/<slug:slug>/publish/", course_studio.course_publish, name="course_publish"),
    path("courses/<slug:slug>/delete/", course_studio.course_delete, name="course_delete"),
    path("courses/<slug:slug>/section/add/", course_studio.section_add, name="section_add"),
    path("courses/<slug:slug>/section/<int:sid>/edit/", course_studio.section_edit, name="section_edit"),
    path("courses/<slug:slug>/section/<int:sid>/delete/", course_studio.section_delete, name="section_delete"),
    path("courses/<slug:slug>/section/<int:sid>/lecture/add/", course_studio.lecture_add, name="lecture_add"),
    path("courses/<slug:slug>/lecture/<int:lid>/edit/", course_studio.lecture_edit, name="lecture_edit"),
    path("courses/<slug:slug>/lecture/<int:lid>/delete/", course_studio.lecture_delete, name="lecture_delete"),
]
