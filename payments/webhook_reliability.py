"""
Webhook reliability helpers (SQLite-friendly).

Stripe retries the SAME delivery (same ``event_id``) until it receives 2xx.

Semantics:

- **Processed**: duplicate deliveries are safe HTTP 200 no-ops (handler must stay idempotent too).
- **Failed**: Stripe will retry; we reset the receipt to ``received`` and run the handler again.
- **Idempotency**: ``StripeWebhookReceipt.event_id`` is UNIQUE — concurrent first deliveries use
  ``IntegrityError`` on insert, then ``get()`` the winner row. No ``SELECT FOR UPDATE`` (it
  aggravates SQLite write locks under concurrent webhooks).

Legacy ``register_stripe_event_once`` is insert-only dedupe (does not allow retries after failure).
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import StripeWebhookReceipt

logger = logging.getLogger(__name__)


def claim_webhook_receipt(*, event_id: str, event_type: str) -> StripeWebhookReceipt:
    """
    Ensure a receipt row exists for ``event_id`` and return it.

    Call inside ``transaction.atomic()`` so the receipt row participates in the same transaction
    as ``mark_receipt_processed`` / ``mark_receipt_failed``.

    Does **not** use ``select_for_update`` (poor fit for SQLite under concurrent webhook POSTs).

    Callers should:

    - If ``receipt.status == processed``: return HTTP 200 without calling the handler.
    - If ``receipt.status == failed``: log retry, reset to ``received``, then run handler.
    - Otherwise run handler, then ``mark_receipt_processed`` or ``mark_receipt_failed``.
    """
    event_id = (event_id or "").strip()
    if not event_id:
        raise ValueError("Stripe event id is missing")

    try:
        return StripeWebhookReceipt.objects.create(
            event_id=event_id,
            event_type=event_type or "",
            status=StripeWebhookReceipt.Status.RECEIVED,
        )
    except IntegrityError:
        logger.info(
            "Stripe webhook receipt deduped on create (concurrent insert) event_id=%s",
            event_id,
        )
        return StripeWebhookReceipt.objects.get(event_id=event_id)


# Backwards-compatible name used by older call sites / docs.
claim_webhook_receipt_locked = claim_webhook_receipt


def register_stripe_event_once(*, event_id: str, event_type: str) -> tuple[bool, StripeWebhookReceipt | None]:
    """
    Deprecated path: insert-only dedupe (does not allow retries after failure).

    Kept for compatibility; new code should use ``claim_webhook_receipt``.
    """
    event_id = (event_id or "").strip()
    if not event_id:
        return True, None

    try:
        with transaction.atomic():
            receipt = StripeWebhookReceipt.objects.create(event_id=event_id, event_type=event_type or "")
        return True, receipt
    except IntegrityError:
        existing = StripeWebhookReceipt.objects.filter(event_id=event_id).first()
        return False, existing


def mark_receipt_processed(receipt: StripeWebhookReceipt | None) -> None:
    if not receipt or not getattr(receipt, "pk", None):
        return
    StripeWebhookReceipt.objects.filter(pk=receipt.pk).update(
        status=StripeWebhookReceipt.Status.PROCESSED,
        processed_at=timezone.now(),
        error_message="",
    )


def mark_receipt_failed(receipt: StripeWebhookReceipt | None, error_message: str) -> None:
    if not receipt or not getattr(receipt, "pk", None):
        return
    StripeWebhookReceipt.objects.filter(pk=receipt.pk).update(
        status=StripeWebhookReceipt.Status.FAILED,
        processed_at=timezone.now(),
        error_message=(error_message or "")[:4000],
    )
