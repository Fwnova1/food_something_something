"""Stripe SDK: Checkout Sessions, webhook signature verification, refunds."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-11-20.acacia"


class CheckoutSessionError(Exception):
    """Stripe Checkout Session API failure."""


def configure_stripe() -> bool:
    secret = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    stripe.api_key = secret or None
    stripe.api_version = getattr(settings, "STRIPE_API_VERSION", "") or DEFAULT_API_VERSION
    return bool(secret)


def _money_to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_checkout_session_for_order(order, *, user_id: int, currency: str, success_url: str, cancel_url: str):
    """
    Server-priced Stripe Checkout Session (``mode="payment"``).
    Line items come only from persisted ``OrderItem`` rows; totals must match ``order.total``.
    """
    from orders.models import OrderItem

    configure_stripe()
    if not stripe.api_key:
        raise CheckoutSessionError("STRIPE_SECRET_KEY is not configured.")

    currency = (currency or "usd").lower()
    line_items = []
    sum_cents = 0

    for oi in OrderItem.objects.filter(order=order).select_related("product"):
        unit_cents = _money_to_cents(oi.price)
        if unit_cents <= 0:
            raise CheckoutSessionError(f"Invalid unit amount for product_id={oi.product_id}")
        sum_cents += unit_cents * oi.quantity
        product_name = (oi.product.name or "Product")[:250]
        line_items.append(
            {
                "price_data": {
                    "currency": currency,
                    "product_data": {
                        "name": product_name,
                        "metadata": {"product_id": str(oi.product_id)},
                    },
                    "unit_amount": unit_cents,
                },
                "quantity": oi.quantity,
            }
        )

    if not line_items:
        raise CheckoutSessionError("Order has no line items.")

    expected_cents = _money_to_cents(order.total)
    if sum_cents != expected_cents:
        logger.error(
            "Order total mismatch order_id=%s cents_sum=%s expected=%s",
            order.id,
            sum_cents,
            expected_cents,
        )
        raise CheckoutSessionError("Order total does not match line items.")

    email = getattr(order.user, "email", None)
    payload = {
        "mode": "payment",
        "client_reference_id": str(order.id),
        "metadata": {"order_id": str(order.id), "user_id": str(user_id)},
        "payment_intent_data": {
            "metadata": {"order_id": str(order.id), "user_id": str(user_id)},
        },
        "line_items": line_items,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if email:
        payload["customer_email"] = email

    try:
        return stripe.checkout.Session.create(**payload)
    except stripe.error.StripeError as exc:
        logger.exception("Stripe Session.create failed order_id=%s", order.id)
        raise CheckoutSessionError(str(exc)) from exc


def construct_webhook_event(payload: bytes, sig_header: str | None) -> Any:
    """
    Verify ``Stripe-Signature`` using raw POST body bytes (must not pre-parse JSON).
    """
    configure_stripe()
    wh_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""
    if not wh_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
    if sig_header is None or not str(sig_header).strip():
        raise ValueError("Missing Stripe-Signature header")
    try:
        return stripe.Webhook.construct_event(payload, sig_header, wh_secret)
    except stripe.error.StripeError as exc:
        raise ValueError(str(exc)) from exc


def create_refund_for_payment_intent(payment_intent_id: str) -> None:
    configure_stripe()
    if not payment_intent_id:
        logger.warning("Refund skipped: empty payment_intent_id")
        return
    try:
        stripe.Refund.create(payment_intent=payment_intent_id)
    except stripe.error.StripeError:
        logger.exception("Stripe Refund.create failed pi=%s", payment_intent_id)
        raise
