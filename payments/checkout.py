"""Create ``payment_pending`` orders and open Stripe Checkout Sessions (test keys only)."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from orders.models import Cart, CartItem, Order, OrderItem

from .constants import ORDER_STATUS_PAYMENT_PENDING
from .models import Payment
from .stripe_service import CheckoutSessionError, create_checkout_session_for_order

logger = logging.getLogger(__name__)


class CheckoutPreparationError(Exception):
    """Cart validation / preparation failed before Stripe."""


def _require_test_mode_keys() -> None:
    secret = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not secret.startswith("sk_test_"):
        raise CheckoutPreparationError(
            "Stripe test mode required: STRIPE_SECRET_KEY must start with sk_test_."
        )
    pub = getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or ""
    if pub and not pub.startswith("pk_test_"):
        raise CheckoutPreparationError(
            "Stripe test mode required: STRIPE_PUBLISHABLE_KEY must start with pk_test_ when set."
        )


@transaction.atomic
def create_payment_pending_order_from_cart(
    user,
    *,
    delivery_address: str,
    delivery_postcode: str,
    customer_note: str,
) -> Order:
    """Persist ``Order`` + ``OrderItem`` from cart; ``payment_pending``; no stock change; cart kept."""
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
    """Create Stripe Checkout Session and ``Payment`` row; returns ``(checkout_url, payment)``."""
    _require_test_mode_keys()

    currency = (getattr(settings, "STRIPE_CHECKOUT_CURRENCY", None) or "usd").lower()

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

    url = getattr(session, "url", None)
    if not url:
        logger.error("Stripe Session missing url order_id=%s", order.id)
        payment.delete()
        raise CheckoutSessionError("Stripe did not return a checkout URL.")

    return url, payment


def abandon_payment_pending_order(order: Order) -> None:
    Payment.objects.filter(order=order).delete()
    order.delete()
