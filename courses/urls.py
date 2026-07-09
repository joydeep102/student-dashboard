from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    path("courses/", views.catalog, name="catalog"),
    path("batch/<slug:code>/", views.batch_detail, name="batch"),
    path("batch/<slug:code>/lesson/<int:pk>/", views.lesson_view, name="lesson"),
    path("batch/<slug:code>/lesson/<int:pk>/source/", views.lesson_source, name="lesson_source"),
    path("batch/<slug:code>/lesson/<int:pk>/progress/", views.lesson_progress, name="lesson_progress"),
    # Recorded-course checkout
    path("batch/<slug:code>/checkout/", views.checkout, name="checkout"),
    path("batch/<slug:code>/checkout/register/", views.checkout_register, name="checkout_register"),
    path("batch/<slug:code>/checkout/upi/", views.upi_submit, name="upi_submit"),
    path("batch/<slug:code>/checkout/razorpay/order/", views.razorpay_order, name="razorpay_order"),
    path("batch/<slug:code>/checkout/razorpay/verify/", views.razorpay_verify, name="razorpay_verify"),
    path("payments/razorpay/webhook/", views.razorpay_webhook, name="razorpay_webhook"),
]
