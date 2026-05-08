from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhook/", views.stripe_webhook_view, name="stripe_webhook"),
    path("checkout/success/", views.checkout_success_view, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel_view, name="checkout_cancel"),
]
