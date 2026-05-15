"""
Payment event logging utilities (append-only audit rows on ``Payment``).

These events power **internal** timelines (e.g. Django admin on ``Payment``). Customer-facing
pages must not render ``event_type`` / raw messages; use payment status and
``build_customer_payment_status_summary`` instead.

Failures here must never break checkout, webhooks, or admin operations; logging errors are
swallowed (but emitted to logs).
"""

from __future__ import annotations

import logging

from .models import Payment, PaymentEvent

logger = logging.getLogger(__name__)


def log_payment_event(
    payment: Payment,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    """
    Append a PaymentEvent row for the given payment.

    This function is intentionally non-raising: event logging should never break payment flows.
    """

    if not payment or not getattr(payment, "pk", None):
        return

    try:
        PaymentEvent.objects.create(
            payment=payment,
            event_type=str(event_type)[:64],
            message=str(message),
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Failed to log payment event payment_id=%s type=%s", getattr(payment, "pk", None), event_type)

