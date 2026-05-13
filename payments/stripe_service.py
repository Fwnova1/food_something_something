"""Stripe SDK: Checkout Sessions, webhook signature verification, refunds."""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-11-20.acacia"

# Methods we allow when demo card-only is off (keeps Checkout predictable; unknown types are dropped).
_CHECKOUT_PAYMENT_METHOD_ALLOWLIST = frozenset({"card", "link"})


class CheckoutSessionError(Exception):
    """Stripe Checkout Session API failure."""


def configure_stripe() -> bool:
    secret = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    stripe.api_key = secret or None
    stripe.api_version = getattr(settings, "STRIPE_API_VERSION", "") or DEFAULT_API_VERSION
    return bool(secret)


def _money_to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_effective_checkout_payment_method_types() -> list[str]:
    """
    Payment methods sent to Stripe Checkout for the customer storefront.

    With ``STRIPE_CHECKOUT_DEMO_CARD_ONLY`` True (default), only ``card`` is used so demos stay
    a simple card flow and do not surface extra methods from env or the Stripe Dashboard.

    When demo card-only is False, ``STRIPE_CHECKOUT_PAYMENT_METHOD_TYPES`` is parsed and filtered
    to supported entries (``card`` and optionally ``link``).
    """
    if getattr(settings, "STRIPE_CHECKOUT_DEMO_CARD_ONLY", True):
        return ["card"]
    raw = getattr(settings, "STRIPE_CHECKOUT_PAYMENT_METHOD_TYPES", None) or ["card"]
    if isinstance(raw, str):
        parts = [raw]
    else:
        parts = list(raw)
    out: list[str] = []
    for x in parts:
        if not isinstance(x, str):
            continue
        t = x.strip().lower()
        if t and t in _CHECKOUT_PAYMENT_METHOD_ALLOWLIST and t not in out:
            out.append(t)
    return out or ["card"]


def create_checkout_session_for_order(order, *, user_id: int, currency: str, success_url: str, cancel_url: str):
    """
    Server-priced Stripe Checkout Session (``mode="payment"``).
    Line items come only from persisted ``OrderItem`` rows; totals must match ``order.total``.
    """
    from orders.models import OrderItem

    configure_stripe()
    if not stripe.api_key:
        logger.error("Stripe Checkout aborted: secret key not configured.")
        raise CheckoutSessionError("We couldn't start checkout right now. Please try again later.")

    currency = (currency or "usd").lower()
    line_items = []
    sum_cents = 0

    for oi in OrderItem.objects.filter(order=order).select_related("product"):
        unit_cents = _money_to_cents(oi.price)
        if unit_cents <= 0:
            logger.error("Invalid checkout unit amount order_id=%s product_id=%s", order.id, oi.product_id)
            raise CheckoutSessionError("Your order can't be paid right now. Please refresh your cart or contact support.")
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
    pm_types = get_effective_checkout_payment_method_types()
    payload["payment_method_types"] = pm_types
    if email:
        payload["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**payload)
        # Event logging is best-effort and must not affect checkout.
        try:
            from .events import log_payment_event
            from .models import Payment

            payment = Payment.objects.filter(order=order).order_by("-created_at").first()
            if payment:
                log_payment_event(
                    payment,
                    "stripe_session_created",
                    "Stripe Checkout Session created.",
                    metadata={"session_id": getattr(session, "id", ""), "order_id": str(getattr(order, "id", ""))},
                )
        except Exception:
            logger.exception("Payment event log failed for stripe_session_created order_id=%s", getattr(order, "id", None))

        return session
    except stripe.error.StripeError as exc:
        logger.exception("Stripe Session.create failed order_id=%s err=%s", order.id, exc)
        raise CheckoutSessionError("We couldn't connect to our payment provider. Please try again.") from exc


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


def create_refund_for_payment_intent(
    payment_intent_id: str,
    *,
    idempotency_key: str | None = None,
    metadata: dict[str, str] | None = None,
):
    """
    Create a refund for a PaymentIntent with optional idempotency + metadata.

    Stripe idempotency is critical for production safety (double-clicks, retries, timeouts).
    """
    configure_stripe()
    if not payment_intent_id:
        logger.warning("Refund skipped: empty payment_intent_id")
        raise ValueError("Empty payment_intent_id")

    params: dict[str, object] = {"payment_intent": payment_intent_id}
    if metadata:
        params["metadata"] = metadata

    request_opts = {}
    if idempotency_key:
        request_opts["idempotency_key"] = idempotency_key

    try:
        # Idempotency key is supplied by refund_service (one stable key per RefundRequest).
        return stripe.Refund.create(**params, **request_opts)
    except stripe.error.StripeError:
        logger.exception("Stripe Refund.create failed pi=%s", payment_intent_id)
        raise
