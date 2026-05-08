"""Human-readable payment summaries for templates."""

from __future__ import annotations

from orders.models import Order

from .models import Payment


def summarize_payment_for_order(order: Order) -> str:
    """Return ``paid``, ``pending``, ``failed``, ``refunded``, or ``unknown``."""
    payment = order.payments.order_by("-created_at").first()
    if not payment:
        return "unknown"

    status = payment.status
    if status == Payment.Status.SUCCEEDED:
        return "paid"
    if status in (Payment.Status.PENDING, Payment.Status.PROCESSING):
        return "pending"
    if status == Payment.Status.FAILED:
        return "failed"
    if status == Payment.Status.REFUNDED:
        return "refunded"
    return "unknown"


def payment_status_label(slug: str) -> str:
    mapping = {
        "paid": "Paid",
        "pending": "Pending",
        "failed": "Failed",
        "refunded": "Refunded",
        "unknown": "—",
    }
    return mapping.get(slug, slug.title())
