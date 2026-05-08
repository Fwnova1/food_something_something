"""Stripe webhook fulfillment: idempotent stock decrement, cart clear, order promotion."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from orders.models import Cart, CartItem, Order, OrderItem
from products.models import Product

from .constants import ORDER_STATUS_AWAITING_PRODUCER, ORDER_STATUS_PAYMENT_PENDING
from .models import Payment

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


def _handle_checkout_session_completed(event) -> None:
    session = _dig(event, "data", "object")
    session_id = _dig(session, "id")
    if not session_id:
        logger.warning("checkout.session.completed missing session id")
        return

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .filter(stripe_checkout_session_id=session_id)
            .select_related("order", "order__user")
            .first()
        )
        if not payment:
            logger.error("Payment row missing for session_id=%s", session_id)
            return

        if payment.status == Payment.Status.SUCCEEDED:
            logger.info("Duplicate checkout.session.completed ignored payment_id=%s", payment.pk)
            return

        if payment.status in (Payment.Status.FAILED, Payment.Status.REFUNDED):
            logger.warning(
                "checkout.session.completed ignored for terminal payment status=%s payment_id=%s",
                payment.status,
                payment.pk,
            )
            return

        order = payment.order
        if not order:
            logger.error("Payment %s has no linked order for session_id=%s", payment.pk, session_id)
            return

        order_locked = Order.objects.select_for_update().get(pk=order.pk)

        md_session = _dig(session, "metadata")
        md_order_id = _meta_value(md_session, "order_id")
        md_user_id = _meta_value(md_session, "user_id")

        if md_order_id and md_order_id != str(order_locked.id):
            logger.error(
                "Metadata order_id mismatch session_order=%s db_order=%s",
                md_order_id,
                order_locked.id,
            )
            raise ValueError("order_id metadata mismatch")

        if md_user_id and md_user_id != str(payment.user_id):
            logger.error("Metadata user_id mismatch for payment_id=%s", payment.pk)
            raise ValueError("user_id metadata mismatch")

        pay_status = _dig(session, "payment_status")
        pay_norm = str(pay_status).strip().lower() if pay_status is not None else ""
        if pay_norm != "paid":
            logger.warning(
                "Skipping fulfillment until Checkout is paid payment_status=%s session_id=%s",
                pay_status,
                session_id,
            )
            return

        if payment.amount != order_locked.total:
            logger.error(
                "payment.amount mismatch order_id=%s payment_amount=%s order_total=%s",
                order_locked.id,
                payment.amount,
                order_locked.total,
            )
            raise ValueError("payment amount mismatch")

        amount_total = _dig(session, "amount_total")
        currency = (str(_dig(session, "currency") or payment.currency or "usd")).lower()
        if amount_total is not None and int(amount_total) != _money_to_cents(order_locked.total):
            logger.error(
                "Stripe amount_total mismatch order_id=%s cents_stripe=%s cents_order=%s",
                order_locked.id,
                amount_total,
                _money_to_cents(order_locked.total),
            )
            raise ValueError("amount_total mismatch")

        if currency and currency != (payment.currency or "usd").lower():
            logger.error("Currency mismatch order_id=%s", order_locked.id)
            raise ValueError("currency mismatch")

        if order_locked.status != ORDER_STATUS_PAYMENT_PENDING:
            logger.info(
                "Order not in payment_pending; skipping fulfillment order_id=%s status=%s",
                order_locked.id,
                order_locked.status,
            )
            return

        payment_intent = _dig(session, "payment_intent")
        pi_id = payment_intent if isinstance(payment_intent, str) else _dig(payment_intent, "id", default="")
        if pi_id:
            payment.stripe_payment_intent_id = pi_id

        for oi in OrderItem.objects.select_related("product").filter(order=order_locked):
            product = oi.product
            updated = Product.objects.filter(
                pk=product.pk, stock_quantity__gte=oi.quantity
            ).update(stock_quantity=F("stock_quantity") - oi.quantity)
            if updated != 1:
                logger.error(
                    "Insufficient stock at fulfillment product_id=%s need=%s",
                    product.id,
                    oi.quantity,
                )
                raise RuntimeError("insufficient stock at fulfillment")

        user = order_locked.user
        try:
            cart = Cart.objects.select_for_update().get(user=user)
        except Cart.DoesNotExist:
            cart = None
        if cart is not None:
            CartItem.objects.filter(cart=cart).delete()

        now = timezone.now()
        payment.status = Payment.Status.SUCCEEDED
        payment.paid_at = now
        payment.save(update_fields=["status", "paid_at", "stripe_payment_intent_id", "updated_at"])

        order_locked.status = ORDER_STATUS_AWAITING_PRODUCER
        order_locked.save(update_fields=["status"])


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
        pay = Payment.objects.select_for_update().get(pk=payment.pk)
        if pay.status == Payment.Status.SUCCEEDED:
            logger.error("payment_intent.payment_failed after success payment_id=%s", pay.pk)
            return
        if pay.status == Payment.Status.FAILED:
            logger.info("Duplicate payment_intent.payment_failed ignored payment_id=%s", pay.pk)
            return

        pay.status = Payment.Status.FAILED
        pay.save(update_fields=["status", "updated_at"])

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
        pay = Payment.objects.select_for_update().get(pk=payment.pk)
        if pay.status == Payment.Status.REFUNDED:
            logger.info("Duplicate charge.refunded ignored payment_id=%s", pay.pk)
            return
        pay.status = Payment.Status.REFUNDED
        pay.save(update_fields=["status", "updated_at"])
