"""Stripe webhook HTTP endpoint and Checkout return URLs."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from orders.models import Order

from .checkout import abandon_payment_pending_order
from .constants import ORDER_STATUS_PAYMENT_PENDING
from .fulfillment import handle_stripe_event
from .models import Payment
from .stripe_service import configure_stripe, construct_webhook_event

logger = logging.getLogger(__name__)


def _session_meta(session, key: str) -> str:
    md = getattr(session, "metadata", None)
    if md is None:
        return ""
    if isinstance(md, dict):
        return str(md.get(key) or "").strip()
    return str(getattr(md, key, "") or "").strip()


def _stripe_error_parent(exc: BaseException):
    return getattr(exc, "__cause__", None) or getattr(exc, "parent", None)


@csrf_exempt
@require_POST
def stripe_webhook_view(request):
    """Stripe-signed webhook; raw body must not be parsed before verification."""
    max_bytes = int(getattr(settings, "STRIPE_WEBHOOK_MAX_BODY_BYTES", 1048576))
    body = request.body
    if len(body) > max_bytes:
        logger.warning("Rejected Stripe webhook: body too large (%s bytes)", len(body))
        return HttpResponseBadRequest("payload too large")

    sig = request.headers.get("Stripe-Signature") or request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = construct_webhook_event(body, sig)
    except ValueError as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        return HttpResponseBadRequest("invalid signature")

    try:
        handle_stripe_event(event)
    except Exception:
        logger.exception("Stripe webhook handler failed event_type=%s", getattr(event, "type", ""))
        return HttpResponse(status=500)

    return HttpResponse(status=200)


@login_required
def checkout_success_view(request):
    """Browser return URL after Stripe Checkout; webhook performs fulfillment."""
    session_id = (request.GET.get("session_id") or "").strip()
    if not session_id:
        return redirect("order_list")

    configure_stripe()
    if not getattr(settings, "STRIPE_SECRET_KEY", ""):
        return redirect("order_list")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as exc:
        parent = _stripe_error_parent(exc)
        code = getattr(parent, "code", None) or getattr(exc, "code", None)
        logger.warning("Could not retrieve Stripe session session_id=%s code=%s", session_id, code)
        return redirect("order_list")

    order_id = _session_meta(session, "order_id") or getattr(session, "client_reference_id", None)
    if not order_id:
        return redirect("order_list")

    try:
        order = Order.objects.get(id=int(order_id), user=request.user)
    except (Order.DoesNotExist, ValueError, TypeError):
        return redirect("order_list")

    payment = Payment.objects.filter(stripe_checkout_session_id=session_id, user=request.user).first()
    if payment and payment.order_id is not None and str(payment.order_id) != str(order.id):
        return redirect("order_list")

    return redirect("order_detail", pk=order.id)


@login_required
def checkout_cancel_view(request):
    """User cancelled Stripe Checkout; drop unpaid draft order if present."""
    session_id = (request.GET.get("session_id") or "").strip()
    if not session_id:
        return redirect("cart")

    configure_stripe()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as exc:
        logger.warning("cancel retrieve session failed session_id=%s err=%s", session_id, exc)
        return redirect("cart")

    if getattr(session, "payment_status", None) == "paid":
        q = urlencode({"session_id": session_id})
        return redirect(f"{reverse('payments:checkout_success')}?{q}")

    order_id = _session_meta(session, "order_id")
    if not order_id:
        return redirect("cart")

    try:
        order = Order.objects.get(id=int(order_id), user=request.user)
    except (Order.DoesNotExist, ValueError, TypeError):
        return redirect("cart")

    payment = Payment.objects.filter(stripe_checkout_session_id=session_id, user=request.user).first()
    if not payment or payment.order_id != order.id:
        return redirect("cart")

    if order.status == ORDER_STATUS_PAYMENT_PENDING:
        abandon_payment_pending_order(order)

    return redirect("cart")
