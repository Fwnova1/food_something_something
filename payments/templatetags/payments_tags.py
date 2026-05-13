"""
Template helpers for **customer** payment UI (storefront orders, refund help).

For admin-style tables and audit detail, use ``payments.display`` helpers meant for staff
(``build_payment_history_rows``, ``stripe_reference_summary``, etc.) in admin templates only.
"""

from django import template

from payments.models import Payment, RefundRequest
from payments.display import (
    build_customer_payment_status_summary,
    customer_payment_status_label,
    customer_refund_request_status_label,
    format_usd,
    payment_status_label,
    summarize_payment_for_order,
)

register = template.Library()

# --- Order-level slugs (templates that branch on paid/pending/failed) ---


@register.filter
def order_payment_status(order):
    return summarize_payment_for_order(order)


@register.filter
def payment_status_display(slug: str) -> str:
    """Map ``summarize_payment_for_order`` slug to a short label (lists, badges)."""
    return payment_status_label(slug)


@register.filter
def usd(value) -> str:
    """Format a money value as USD with exactly two decimal places (e.g. ``$16.22``)."""
    return format_usd(value)


@register.filter
def customer_payment_status(payment) -> str:
    """Friendly payment status for customer-facing pages (no raw enum / provider jargon)."""
    if not payment:
        return "—"
    return customer_payment_status_label(getattr(payment, "status", "") or "")


@register.filter
def customer_refund_request_status(status) -> str:
    """Friendly refund-request status for customers."""
    if status is None or status == "":
        return "—"
    return customer_refund_request_status_label(str(status))


# --- Customer-safe payment / refund strings (never raw DB tokens or Stripe ids) ---


@register.filter
def customer_order_payment_summary(order) -> str:
    """Plain-language payment summary for an order (no internal audit event names)."""
    if not order:
        return ""
    return build_customer_payment_status_summary(order)


@register.filter
def customer_payment_is_paid(payment) -> bool:
    """True when the latest payment is completed successfully (for storefront branching, not raw status text)."""
    return bool(payment and getattr(payment, "status", None) == Payment.Status.SUCCEEDED)


# --- Refund request state flags (keep templates free of string comparisons to model enums) ---


@register.filter
def customer_refund_request_is_pending(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.PENDING)


@register.filter
def customer_refund_request_is_approved(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.APPROVED)


@register.filter
def customer_refund_request_is_processing(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.PROCESSING)


@register.filter
def customer_refund_request_is_failed(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.FAILED)


@register.filter
def customer_refund_request_is_completed(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.COMPLETED)


@register.filter
def customer_refund_request_is_rejected(rr) -> bool:
    return bool(rr and getattr(rr, "status", None) == RefundRequest.Status.REJECTED)
