"""Create ``payment_pending`` orders and open hosted checkout sessions with the configured provider."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from orders.models import Cart, CartItem, Order, OrderItem

from .constants import ORDER_STATUS_PAYMENT_PENDING
from .models import Payment
from .stripe_service import CheckoutSessionError, create_checkout_session_for_order
from .events import log_payment_event

logger = logging.getLogger(__name__)


class CheckoutPreparationError(Exception):
    """Cart validation / preparation failed before opening hosted checkout."""


def _require_storefront_checkout_keys() -> None:
    """Demo-safe storefront: only allow test-mode provider keys (never live keys in this path)."""
    secret = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not secret.startswith("sk_test_"):
        logger.error("Checkout blocked: secret key is not a permitted demo/test configuration.")
        raise CheckoutPreparationError("Payments are temporarily unavailable. Please try again later.")
    pub = getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or ""
    if pub and not pub.startswith("pk_test_"):
        logger.error("Checkout blocked: publishable key is not a permitted demo/test configuration.")
        raise CheckoutPreparationError("Payments are temporarily unavailable. Please try again later.")


@transaction.atomic
def create_payment_pending_order_from_cart(
    user,
    *,
    delivery_address: str,
    delivery_postcode: str,
    customer_note: str,
) -> Order:
    """
    Persist ``Order`` + ``OrderItem`` from the cart under ``payment_pending``.

    Stock is not decremented here (reservation happens after successful payment in fulfillment).
    The cart rows are left in place so the shopper can retry checkout if needed.
    """
    cart, _ = Cart.objects.get_or_create(user=user)
    cart = Cart.objects.select_for_update().get(pk=cart.pk)

    lines = list(
        CartItem.objects.select_related("product")
        .filter(cart=cart)
        .select_for_update()
    )
    if not lines:
        raise CheckoutPreparationError("Your cart is empty.")

    total = Decimal("0.00")
    for item in lines:
        if item.quantity > item.product.stock_quantity:
            raise CheckoutPreparationError(
                f"Insufficient stock for {item.product.name}. Update your cart and try again."
            )
        total += item.product.price * item.quantity

    order = Order.objects.create(
        user=user,
        total=total,
        status=ORDER_STATUS_PAYMENT_PENDING,
        delivery_address=delivery_address,
        delivery_postcode=delivery_postcode,
        customer_note=customer_note,
    )

    for item in lines:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price,
        )

    return order


def start_stripe_checkout_for_order(order: Order, *, user, success_url: str, cancel_url: str) -> tuple[str, Payment]:
    """
    Open Stripe Checkout: create session, persist ``Payment`` (pending), and return the hosted URL.

    Raises ``CheckoutPreparationError`` if keys are not demo-safe, or ``CheckoutSessionError`` if Stripe fails.
    """
    _require_storefront_checkout_keys()

    currency = (getattr(settings, "STRIPE_CHECKOUT_CURRENCY", None) or "usd").lower()

    # Checkout start is logged against the soon-to-be-created Payment row.
    session = create_checkout_session_for_order(
        order,
        user_id=user.id,
        currency=currency,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    pi = getattr(session, "payment_intent", None)
    pi_str = ""
    if pi:
        pi_str = pi if isinstance(pi, str) else getattr(pi, "id", "") or str(pi)

    payment = Payment.objects.create(
        user=user,
        order=order,
        amount=order.total,
        currency=currency,
        stripe_checkout_session_id=session.id,
        stripe_payment_intent_id=pi_str,
        status=Payment.Status.PENDING,
        metadata={"order_id": order.id},
    )

    log_payment_event(
        payment,
        "checkout_started",
        "Checkout initiated and Payment row created.",
        metadata={"session_id": session.id, "order_id": str(order.id)},
    )
    log_payment_event(
        payment,
        "stripe_session_created",
        "Stripe Checkout Session created.",
        metadata={"session_id": session.id, "order_id": str(order.id)},
    )

    url = getattr(session, "url", None)
    if not url:
        logger.error("Stripe Session missing url order_id=%s", order.id)
        payment.delete()
        raise CheckoutSessionError("We couldn't start the payment checkout. Please try again.")

    return url, payment


def abandon_payment_pending_order(order: Order) -> None:
    """Remove a never-paid checkout attempt (payment rows then order). Used when the user returns to the cart."""
    Payment.objects.filter(order=order).delete()
    order.delete()
