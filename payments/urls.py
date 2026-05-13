"""
URL routes for payments: provider webhook, hosted checkout return URLs, customer refund help, and operator refund actions.

Namespaced as ``payments:…`` (see ``app_name``).
"""

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhook/", views.stripe_webhook_view, name="stripe_webhook"),
    path("checkout/success/", views.checkout_success_view, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel_view, name="checkout_cancel"),
    path("refunds/request/<int:order_id>/", views.refund_request_view, name="refund_request"),
    path("refunds/inbox/", views.refund_inbox_view, name="refund_inbox"),
    path("refunds/<int:refund_request_id>/approve/", views.refund_approve_view, name="refund_approve"),
    path("refunds/<int:refund_request_id>/reject/", views.refund_reject_view, name="refund_reject"),
    path("refunds/<int:refund_request_id>/process/", views.refund_process_view, name="refund_process"),
    path("refunds/<int:refund_request_id>/delete/", views.refund_delete_view, name="refund_delete"),
]
