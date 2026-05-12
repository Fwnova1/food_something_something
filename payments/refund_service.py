"""
Refund orchestration helpers.

``process_refund_request`` is the single entry point for **Process refund** (admin action,
operator inbox, or future automation). It:

- Executes the refund through Stripe (``Refund.create``) with a **stable idempotency key**
  per ``RefundRequest`` so duplicate clicks, retries, and timeouts do not double-refund.
- Updates ``RefundRequest`` (terminal status, ``stripe_refund_id``, ``processed_at``) and
  ``Payment`` (terminal ``refunded`` / ``partially_refunded``, or ``refund_pending`` only
  while awaiting the gateway).
- Sets ``RefundRequest`` to **processing** in a **committed** transaction *before* the gateway
  call so customer pages show “being processed” immediately.
- Appends ``PaymentEvent`` rows for audit (see ``log_payment_event``).
- Is **idempotent**: replays return ``outcome="already_processed"`` and reconcile payment
  state if the gateway already refunded but local rows were out of sync.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from .models import Payment, RefundRequest
from .stripe_service import create_refund_for_payment_intent
from .events import log_payment_event

logger = logging.getLogger(__name__)


class RefundProcessResult(NamedTuple):
    refund_request: RefundRequest
    outcome: str  # "processed" | "already_processed"


class _StripeRefundContext(NamedTuple):
    refund_request_id: int
    payment_intent_id: str
    idempotency_key: str
    metadata: dict


def _refund_idempotency_key(refund_request: RefundRequest) -> str:
    # Stable, deterministic key per refund request (marketplace-grade safety property).
    return f"brfn_refund_request:{refund_request.pk}"


def _order_amount_cents(payment: Payment) -> int:
    return int((payment.amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _payment_terminal_status_from_refund_amount(*, payment: Payment, refund_amount_cents: int | None) -> str:
    """Return Payment.Status.REFUNDED or PARTIALLY_REFUNDED from gateway refund amount (cents)."""
    if refund_amount_cents is None or refund_amount_cents <= 0:
        return Payment.Status.REFUNDED
    order_cents = _order_amount_cents(payment)
    if order_cents > 0 and refund_amount_cents < order_cents:
        return Payment.Status.PARTIALLY_REFUNDED
    return Payment.Status.REFUNDED


def _finalize_refund_request_and_payment(
    *,
    rr: RefundRequest,
    payment: Payment,
    stripe_refund_id: str,
    refund_amount_cents: int | None,
) -> None:
    now = timezone.now()
    terminal = _payment_terminal_status_from_refund_amount(
        payment=payment, refund_amount_cents=refund_amount_cents
    )
    payment.status = terminal
    payment.save(update_fields=["status", "updated_at"])

    rr.stripe_refund_id = stripe_refund_id
    rr.status = RefundRequest.Status.COMPLETED
    rr.processed_at = now
    rr.save(update_fields=["stripe_refund_id", "status", "processed_at"])

    logger.info(
        "Refund processed refund_request_id=%s stripe_refund_id=%s payment_status=%s",
        rr.pk,
        stripe_refund_id,
        terminal,
    )
    log_payment_event(
        payment,
        "refund_completed",
        "Refund completed via process_refund_request (gateway + records updated).",
        metadata={
            "refund_request_id": str(rr.pk),
            "stripe_refund_id": stripe_refund_id,
            "payment_status": terminal,
            "source": "process_refund_request",
        },
    )


def _reconcile_already_recorded_refund(
    *,
    rr: RefundRequest,
    payment: Payment,
) -> RefundProcessResult:
    """
    Idempotent path: gateway refund already tied to this request (stripe_refund_id set).

    Ensures RefundRequest is COMPLETED and payment is in a terminal refunded state so
    replays and admin retries are safe.
    """
    now = timezone.now()
    changed = False
    if rr.status != RefundRequest.Status.COMPLETED:
        rr.status = RefundRequest.Status.COMPLETED
        rr.processed_at = rr.processed_at or now
        rr.save(update_fields=["status", "processed_at"])
        changed = True

    if payment.status not in (
        Payment.Status.REFUNDED,
        Payment.Status.PARTIALLY_REFUNDED,
    ):
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["status", "updated_at"])
        changed = True

    if changed:
        log_payment_event(
            payment,
            "refund_process_reconciled",
            "Refund request replay: reconciled local payment/refund rows with existing gateway refund.",
            metadata={
                "refund_request_id": str(rr.pk),
                "stripe_refund_id": rr.stripe_refund_id or "",
                "source": "process_refund_request_idempotent",
            },
        )
    else:
        logger.info(
            "Refund process idempotent skip refund_request_id=%s payment_id=%s",
            rr.pk,
            payment.pk,
        )

    return RefundProcessResult(refund_request=rr, outcome="already_processed")


def _refund_mark_failed_and_revert_payment(refund_request_id: int) -> None:
    """
    After a failed gateway attempt: mark the request failed and put the payment back to succeeded
    so the customer is not stuck on “refund in progress” without a terminal outcome.
    """
    with transaction.atomic():
        rr = RefundRequest.objects.select_for_update().get(pk=refund_request_id)
        payment = Payment.objects.select_for_update().get(pk=rr.payment_id)
        if (rr.stripe_refund_id or "").strip():
            return
        changed = False
        if rr.status == RefundRequest.Status.PROCESSING:
            rr.status = RefundRequest.Status.FAILED
            rr.save(update_fields=["status"])
            changed = True
        if payment.status == Payment.Status.REFUND_PENDING:
            payment.status = Payment.Status.SUCCEEDED
            payment.save(update_fields=["status", "updated_at"])
            changed = True
        if changed:
            log_payment_event(
                payment,
                "refund_process_failed",
                "Refund attempt did not complete; records reverted for retry or follow-up.",
                metadata={"refund_request_id": str(rr.pk), "source": "process_refund_request"},
            )


def _refund_prepare_committed(refund_request_id: int) -> RefundProcessResult | _StripeRefundContext:
    """
    Validate, move the request to **processing**, and move payment to **refund_pending** when needed.

    Commits before returning ``_StripeRefundContext`` so customer-facing status updates immediately.
    """
    with transaction.atomic():
        try:
            rr = (
                RefundRequest.objects.select_for_update()
                .select_related("payment")
                .get(pk=refund_request_id)
            )
            payment = Payment.objects.select_for_update().get(pk=rr.payment_id)
        except RefundRequest.DoesNotExist as exc:
            raise ValueError("Refund request not found.") from exc
        except Payment.DoesNotExist as exc:
            raise ValueError("Linked payment row is missing.") from exc

        stripe_rid = (rr.stripe_refund_id or "").strip()
        if stripe_rid:
            return _reconcile_already_recorded_refund(rr=rr, payment=payment)

        if rr.status == RefundRequest.Status.COMPLETED:
            raise ValueError(
                "This refund is already marked complete, but the confirmation on file is missing. Contact support."
            )

        if rr.status not in (
            RefundRequest.Status.APPROVED,
            RefundRequest.Status.PROCESSING,
            RefundRequest.Status.FAILED,
        ):
            raise ValueError("Refund request must be approved before processing.")

        if payment.status in (Payment.Status.REFUNDED, Payment.Status.PARTIALLY_REFUNDED):
            raise ValueError("This order is already in a refunded state and cannot be processed again.")

        if payment.status not in (Payment.Status.SUCCEEDED, Payment.Status.REFUND_PENDING):
            raise ValueError("Only a completed payment (or one already being refunded) can be processed here.")

        if not payment.stripe_payment_intent_id:
            raise ValueError(
                "A payment reference needed for a refund is missing. Please contact support with your order number."
            )

        if rr.status in (RefundRequest.Status.APPROVED, RefundRequest.Status.FAILED):
            now = timezone.now()
            rr.status = RefundRequest.Status.PROCESSING
            rr.processing_started_at = now
            rr.save(update_fields=["status", "processing_started_at"])

        if payment.status == Payment.Status.SUCCEEDED:
            payment.status = Payment.Status.REFUND_PENDING
            payment.save(update_fields=["status", "updated_at"])
            log_payment_event(
                payment,
                "refund_requested",
                "Refund processing initiated (contacting payment processor).",
                metadata={"refund_request_id": str(rr.pk), "source": "process_refund_request"},
            )

        return _StripeRefundContext(
            refund_request_id=rr.pk,
            payment_intent_id=payment.stripe_payment_intent_id.strip(),
            idempotency_key=_refund_idempotency_key(rr),
            metadata={
                "refund_request_id": str(rr.pk),
                "payment_id": str(payment.pk),
                "order_id": str(payment.order_id or ""),
                "user_id": str(payment.user_id),
            },
        )


def process_refund_request(refund_request_id: int) -> RefundProcessResult:
    """
    Execute gateway refund for an **approved**, **processing** (resume), or **failed** (retry)
    refund request and persist outcomes.

    Duplicate / concurrent calls:
    - Same idempotency key → gateway returns the same Refund; we persist once then short-circuit.
    - ``stripe_refund_id`` already set → reconcile and return ``already_processed``.
    """

    # Flow: (1) committed DB prepare so customers see processing, (2) Stripe Refund.create,
    # (3) atomic finalize or failure handler that reverts payment out of refund_pending.
    stage1 = _refund_prepare_committed(refund_request_id)
    if isinstance(stage1, RefundProcessResult):
        return stage1

    try:
        refund = create_refund_for_payment_intent(
            stage1.payment_intent_id,
            idempotency_key=stage1.idempotency_key,
            metadata=stage1.metadata,
        )
    except Exception as exc:
        logger.exception("Refund gateway call failed refund_request_id=%s", refund_request_id)
        _refund_mark_failed_and_revert_payment(refund_request_id)
        raise ValueError(
            "We could not complete the refund yet. Please try again in a moment, or contact support with your order number."
        ) from exc

    new_rid = getattr(refund, "id", None) or ""
    if not new_rid:
        _refund_mark_failed_and_revert_payment(refund_request_id)
        raise ValueError(
            "The payment processor did not return a refund confirmation. Please try again or contact support."
        )

    try:
        refund_amount_cents = int(getattr(refund, "amount", None) or 0)
    except (TypeError, ValueError):
        refund_amount_cents = None

    with transaction.atomic():
        rr = RefundRequest.objects.select_for_update().get(pk=refund_request_id)
        payment = Payment.objects.select_for_update().get(pk=rr.payment_id)
        if (rr.stripe_refund_id or "").strip():
            return _reconcile_already_recorded_refund(rr=rr, payment=payment)

        _finalize_refund_request_and_payment(
            rr=rr,
            payment=payment,
            stripe_refund_id=str(new_rid),
            refund_amount_cents=refund_amount_cents,
        )

    rr.refresh_from_db()
    return RefundProcessResult(refund_request=rr, outcome="processed")
