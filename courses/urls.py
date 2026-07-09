from django.urls import path

from . import course_views, views

app_name = "courses"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    # Public recorded-course catalog (the price URL to link from the main site).
    path("courses/", course_views.catalog, name="catalog"),
    # Udemy-style recorded courses
    path("course/<slug:slug>/", course_views.course_landing, name="course"),
    path("course/<slug:slug>/learn/<int:pk>/", course_views.learn, name="learn"),
    path("course/<slug:slug>/learn/<int:pk>/source/", course_views.lecture_source, name="lecture_source"),
    path("course/<slug:slug>/learn/<int:pk>/progress/", course_views.lecture_progress, name="lecture_progress"),
    path("course/<slug:slug>/enroll/", course_views.checkout, name="course_checkout"),
    path("course/<slug:slug>/enroll/register/", course_views.checkout_register, name="course_register"),
    path("course/<slug:slug>/enroll/upi/", course_views.upi_submit, name="course_upi_submit"),
    path("course/<slug:slug>/enroll/razorpay/order/", course_views.razorpay_order, name="course_razorpay_order"),
    path("course/<slug:slug>/enroll/razorpay/verify/", course_views.razorpay_verify, name="course_razorpay_verify"),
    path("payments/course/razorpay/webhook/", course_views.razorpay_webhook, name="course_razorpay_webhook"),
    # Live cohorts (batches) — unchanged
    path("batch/<slug:code>/", views.batch_detail, name="batch"),
    path("batch/<slug:code>/lesson/<int:pk>/", views.lesson_view, name="lesson"),
    path("batch/<slug:code>/lesson/<int:pk>/source/", views.lesson_source, name="lesson_source"),
    path("batch/<slug:code>/lesson/<int:pk>/progress/", views.lesson_progress, name="lesson_progress"),
    path("batch/<slug:code>/checkout/", views.checkout, name="checkout"),
    path("batch/<slug:code>/checkout/register/", views.checkout_register, name="checkout_register"),
    path("batch/<slug:code>/checkout/upi/", views.upi_submit, name="upi_submit"),
    path("batch/<slug:code>/checkout/razorpay/order/", views.razorpay_order, name="razorpay_order"),
    path("batch/<slug:code>/checkout/razorpay/verify/", views.razorpay_verify, name="razorpay_verify"),
    path("payments/razorpay/webhook/", views.razorpay_webhook, name="razorpay_webhook"),
]
