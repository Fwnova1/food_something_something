"""Stripe webhook fulfillment: idempotent stock decrement, cart clear, order promotion."""

from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from orders.models import Cart, CartItem, Order, OrderItem
from products.models import Product

from .constants import ORDER_STATUS_AWAITING_PRODUCER, ORDER_STATUS_PAYMENT_PENDING
from .models import Payment
from .events import log_payment_event

logger = logging.getLogger(__name__)


def _dig(obj, *keys, default=None):
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        else:
            cur = getattr(cur, key, default)
    return cur


def _meta_value(md, key: str) -> str:
    """Supports dict metadata or Stripe metadata objects."""
    if md is None:
        return ""
    if isinstance(md, dict):
        return str(md.get(key) or "").strip()
    val = getattr(md, key, None)
    return str(val or "").strip()


def _money_to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def handle_stripe_event(event) -> None:
    etype = getattr(event, "type", None) or _dig(event, "type")
    eid = getattr(event, "id", None) or _dig(event, "id")
    logger.info("Stripe webhook received event_id=%s type=%s", eid, etype)
    if etype == "checkout.session.completed":
        _handle_checkout_session_completed(event)
    elif etype == "payment_intent.payment_failed":
        _handle_payment_intent_failed(event)
    elif etype == "charge.refunded":
        _handle_charge_refunded(event)
    else:
        logger.info("Stripe webhook ignored event_type=%s", etype)


def _wait_for_concurrent_checkout_fulfillment(*, payment_pk: int, max_wait_s: float = 8.0) -> bool:
    """
    If another webhook worker claimed ``pending -> processing`` first, wait until it finishes.

    Returns True if payment reached ``succeeded`` (duplicate delivery; safe no-op).
    Returns False if we should continue (caller may retry claim) or give up.
    """
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        st = Payment.objects.filter(pk=payment_pk).values_list("status", flat=True).first()
        if st == Payment.Status.SUCCEEDED:
            return True
        if st == Payment.Status.PENDING:
            return False
        time.sleep(0.05)
    return Payment.objects.filter(pk=payment_pk, status=Payment.Status.SUCCEEDED).exists()


def _handle_checkout_session_completed(event) -> None:
    session = _dig(event, "data", "object")
    session_id = _dig(session, "id")
    if not session_id:
        logger.warning("checkout.session.completed missing session id")
        return

    with transaction.atomic():
        payment = (
            Payment.objects.filter(stripe_checkout_session_id=session_id)
            .select_related("order", "order__user")
            .order_by("-created_at")
            .first()
        )
        if not payment:
            logger.error("Payment row missing for session_id=%s", session_id)
            return

        log_payment_event(
            payment,
            "webhook_received",
            "Stripe webhook received: checkout.session.completed.",
            metadata={"event_type": "checkout.session.completed", "session_id": session_id},
        )

        if payment.status == Payment.Status.SUCCEEDED:
            logger.info("Duplicate checkout.session.completed ignored payment_id=%s", payment.pk)
            return

        if payment.status in (
            Payment.Status.FAILED,
            Payment.Status.REFUNDED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUND_PENDING,
        ):
            logger.warning(
                "checkout.session.completed ignored for terminal payment status=%s payment_id=%s",
                payment.status,
                payment.pk,
            )
            return

        # Serialize concurrent deliveries of the same checkout session without row locks
        # (SQLite-friendly): only one worker may move pending -> processing for this payment row.
        claimed = Payment.objects.filter(
            pk=payment.pk,
            status=Payment.Status.PENDING,
            stripe_checkout_session_id=session_id,
        ).update(status=Payment.Status.PROCESSING)
        if claimed == 0:
            payment.refresh_from_db()
            if payment.status == Payment.Status.SUCCEEDED:
                logger.info("Duplicate checkout.session.completed ignored payment_id=%s", payment.pk)
                return
            if payment.status == Payment.Status.PROCESSING:
                if _wait_for_concurrent_checkout_fulfillment(payment_pk=payment.pk):
                    logger.info(
                        "Concurrent checkout.session.completed finished elsewhere payment_id=%s",
                        payment.pk,
                    )
                    return
                payment.refresh_from_db()
            if payment.status == Payment.Status.SUCCEEDED:
                logger.info(
                    "Concurrent checkout.session.completed finished elsewhere payment_id=%s",
                    payment.pk,
                )
                return
            logger.warning(
                "checkout.session.completed could not claim payment_id=%s status=%s",
                payment.pk,
                payment.status,
            )
            raise RuntimeError("checkout.session.completed claim race unresolved")

        payment = Payment.objects.select_related("order", "order__user").get(pk=payment.pk)

        order = payment.order
        if not order:
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error("Payment %s has no linked order for session_id=%s", payment.pk, session_id)
            return

        order_row = Order.objects.get(pk=order.pk)

        md_session = _dig(session, "metadata")
        md_order_id = _meta_value(md_session, "order_id")
        md_user_id = _meta_value(md_session, "user_id")

        if md_order_id and md_order_id != str(order_row.id):
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error(
                "Metadata order_id mismatch session_order=%s db_order=%s",
                md_order_id,
                order_row.id,
            )
            raise ValueError("order_id metadata mismatch")

        if md_user_id and md_user_id != str(payment.user_id):
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error("Metadata user_id mismatch for payment_id=%s", payment.pk)
            raise ValueError("user_id metadata mismatch")

        pay_status = _dig(session, "payment_status")
        pay_norm = str(pay_status).strip().lower() if pay_status is not None else ""
        if pay_norm != "paid":
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.warning(
                "Skipping fulfillment until Checkout is paid payment_status=%s session_id=%s",
                pay_status,
                session_id,
            )
            return

        if payment.amount != order_row.total:
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error(
                "payment.amount mismatch order_id=%s payment_amount=%s order_total=%s",
                order_row.id,
                payment.amount,
                order_row.total,
            )
            raise ValueError("payment amount mismatch")

        amount_total = _dig(session, "amount_total")
        currency = (str(_dig(session, "currency") or payment.currency or "usd")).lower()
        if amount_total is not None and int(amount_total) != _money_to_cents(order_row.total):
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error(
                "Stripe amount_total mismatch order_id=%s cents_stripe=%s cents_order=%s",
                order_row.id,
                amount_total,
                _money_to_cents(order_row.total),
            )
            raise ValueError("amount_total mismatch")

        if currency and currency != (payment.currency or "usd").lower():
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.error("Currency mismatch order_id=%s", order_row.id)
            raise ValueError("currency mismatch")

        if order_row.status != ORDER_STATUS_PAYMENT_PENDING:
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                status=Payment.Status.PENDING
            )
            logger.info(
                "Order not in payment_pending; skipping fulfillment (idempotent) order_id=%s status=%s payment_id=%s",
                order_row.id,
                order_row.status,
                payment.pk,
            )
            return

        payment_intent = _dig(session, "payment_intent")
        pi_id = payment_intent if isinstance(payment_intent, str) else _dig(payment_intent, "id", default="")
        if pi_id:
            payment.stripe_payment_intent_id = pi_id

        for oi in OrderItem.objects.select_related("product").filter(order=order_row):
            product = oi.product
            updated = Product.objects.filter(
                pk=product.pk, stock_quantity__gte=oi.quantity
            ).update(stock_quantity=F("stock_quantity") - oi.quantity)
            if updated != 1:
                Payment.objects.filter(pk=payment.pk, status=Payment.Status.PROCESSING).update(
                    status=Payment.Status.PENDING
                )
                logger.error(
                    "Insufficient stock at fulfillment product_id=%s need=%s",
                    product.id,
                    oi.quantity,
                )
                raise RuntimeError("insufficient stock at fulfillment")

        log_payment_event(
            payment,
            "fulfillment_started",
            "Fulfillment started: stock decrement and cart clear.",
            metadata={"order_id": str(order_row.id)},
        )

        user = order_row.user
        cart = Cart.objects.filter(user=user).first()
        if cart is not None:
            CartItem.objects.filter(cart=cart).delete()

        now = timezone.now()
        payment.status = Payment.Status.SUCCEEDED
        payment.paid_at = now
        payment.save(update_fields=["status", "paid_at", "stripe_payment_intent_id", "updated_at"])

        log_payment_event(
            payment,
            "payment_succeeded",
            "Payment marked as succeeded from Stripe webhook.",
            metadata={"order_id": str(order_row.id), "session_id": session_id},
        )

        order_row.status = ORDER_STATUS_AWAITING_PRODUCER
        order_row.save(update_fields=["status"])

        log_payment_event(
            payment,
            "fulfillment_completed",
            "Fulfillment completed: order promoted to awaiting_producer.",
            metadata={"order_id": str(order_row.id)},
        )


def _find_payment_by_intent_id(pi_id: str) -> Payment | None:
    if not pi_id:
        return None
    found = (
        Payment.objects.filter(stripe_payment_intent_id=pi_id)
        .select_related("order")
        .order_by("-created_at")
        .first()
    )
    if found:
        return found
    return None


def _handle_payment_intent_failed(event) -> None:
    obj = _dig(event, "data", "object")
    pi_id = _dig(obj, "id")
    payment = _find_payment_by_intent_id(pi_id)
    if not payment:
        meta = _dig(obj, "metadata")
        oid = _meta_value(meta, "order_id")
        if oid:
            try:
                payment = (
                    Payment.objects.filter(order_id=int(oid))
                    .select_related("order")
                    .order_by("-created_at")
                    .first()
                )
            except ValueError:
                payment = None
    if not payment:
        logger.warning("payment_intent.payment_failed: no payment found pi_id=%s", pi_id)
        return

    with transaction.atomic():
        pay = Payment.objects.select_related("order").get(pk=payment.pk)

        log_payment_event(
            pay,
            "webhook_received",
            "Stripe webhook received: payment_intent.payment_failed.",
            metadata={"event_type": "payment_intent.payment_failed", "payment_intent_id": pi_id},
        )

        if pay.status == Payment.Status.SUCCEEDED:
            logger.error("payment_intent.payment_failed after success payment_id=%s", pay.pk)
            return
        if pay.status == Payment.Status.FAILED:
            logger.info("Duplicate payment_intent.payment_failed ignored payment_id=%s", pay.pk)
            return

        updated = Payment.objects.filter(
            pk=pay.pk,
            status__in=(Payment.Status.PENDING, Payment.Status.PROCESSING),
        ).update(status=Payment.Status.FAILED)
        if updated == 0:
            pay.refresh_from_db()
            if pay.status == Payment.Status.FAILED:
                logger.info("Duplicate payment_intent.payment_failed ignored payment_id=%s", pay.pk)
            return

        log_payment_event(
            pay,
            "payment_failed",
            "Payment marked as failed from Stripe webhook.",
            metadata={"payment_intent_id": pi_id},
        )

        order = pay.order
        if order and order.status == ORDER_STATUS_PAYMENT_PENDING:
            oid = order.id
            order.delete()
            logger.info("Removed unpaid order after failed payment order_id=%s", oid)


def _handle_charge_refunded(event) -> None:
    charge = _dig(event, "data", "object")
    pi = _dig(charge, "payment_intent")
    pi_id = pi if isinstance(pi, str) else _dig(pi, "id", default="")
    payment = _find_payment_by_intent_id(pi_id)
    if not payment:
        logger.info("charge.refunded: no payment for pi_id=%s", pi_id)
        return

    with transaction.atomic():
        pay = Payment.objects.select_related("order").get(pk=payment.pk)
        log_payment_event(
            pay,
            "webhook_received",
            "Stripe webhook received: charge.refunded.",
            metadata={"event_type": "charge.refunded", "payment_intent_id": pi_id},
        )
        if pay.status == Payment.Status.REFUNDED:
            logger.info("Duplicate charge.refunded ignored payment_id=%s", pay.pk)
            return

        # Stripe may emit charge.refunded for partial refunds as well.
        amount = _dig(charge, "amount")
        amount_refunded = _dig(charge, "amount_refunded")
        try:
            amount_i = int(amount) if amount is not None else 0
            refunded_i = int(amount_refunded) if amount_refunded is not None else 0
        except (ValueError, TypeError):
            amount_i = 0
            refunded_i = 0

        if amount_i > 0 and 0 < refunded_i < amount_i:
            new_status = Payment.Status.PARTIALLY_REFUNDED
        else:
            new_status = Payment.Status.REFUNDED

        updated = Payment.objects.filter(pk=pay.pk).exclude(status=new_status).update(status=new_status)
        if updated == 0:
            logger.info("Duplicate or idempotent charge.refunded ignored payment_id=%s", pay.pk)
            return

        log_payment_event(
            pay,
            "refund_completed",
            "Refund completed (Stripe charge.refunded).",
            metadata={"payment_intent_id": pi_id, "amount": amount_i, "amount_refunded": refunded_i},
        )
