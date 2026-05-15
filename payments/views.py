"""
Stripe integration views: signed webhooks, checkout return URLs, customer refund help, and operator refund inbox.

* **Customer-facing:** ``refund_request_view`` — creates pending ``RefundRequest`` rows only; no admin or gateway side effects.
* **Operators:** ``refund_inbox_view`` and POST handlers approve/reject/process/delete; settlement calls ``process_refund_request``.
* **Webhooks / success / cancel:** drive ``Payment`` status and order fulfillment via ``fulfillment`` helpers.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from orders.models import Order
from orders.models import OrderItem

from .checkout import abandon_payment_pending_order
from .constants import ORDER_STATUS_PAYMENT_PENDING
from .fulfillment import handle_stripe_event
from .models import Payment, RefundRequest, StripeWebhookReceipt
from .stripe_service import configure_stripe, construct_webhook_event
from .display import (
    build_customer_payment_status_summary,
    customer_refund_open_and_latest,
)
from .events import log_payment_event
from .refund_service import process_refund_request

from .webhook_reliability import (
    claim_webhook_receipt,
    mark_receipt_failed,
    mark_receipt_processed,
)

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
    """
    Stripe-signed webhook; raw body must not be parsed before verification.

    Reliability:

    - ``StripeWebhookReceipt`` rows are UNIQUE on ``event_id`` (insert + ``IntegrityError`` dedupe;
      no ``SELECT FOR UPDATE``, which is hard on SQLite under concurrent webhook POSTs).
    - ``processed``: duplicate deliveries get HTTP 200 without re-running the handler.
    - ``failed``: Stripe retries; we reset to ``received`` and run the handler again.
    - Fulfillment uses atomic ``pending -> processing`` claim on ``Payment`` so concurrent
      ``checkout.session.completed`` handlers cannot double-decrement stock.
    """
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

    event_id = str(getattr(event, "id", "") or "").strip()
    event_type = str(getattr(event, "type", "") or "")
    if not event_id:
        logger.warning("Stripe webhook missing event id")
        return HttpResponseBadRequest("missing event id")

    with transaction.atomic():
        receipt = claim_webhook_receipt(event_id=event_id, event_type=event_type)

        if receipt.status == StripeWebhookReceipt.Status.PROCESSED:
            logger.info(
                "Stripe webhook duplicate delivery (already processed) event_id=%s type=%s",
                event_id,
                event_type,
            )
            return HttpResponse(status=200)

        if receipt.status == StripeWebhookReceipt.Status.FAILED:
            logger.warning(
                "Stripe webhook retry after failure event_id=%s type=%s",
                event_id,
                event_type,
            )
            StripeWebhookReceipt.objects.filter(pk=receipt.pk).update(
                status=StripeWebhookReceipt.Status.RECEIVED,
                error_message="",
                processed_at=None,
            )

        # Best-effort audit trail (may duplicate on retries; handler logs remain authoritative).
        try:
            etype = getattr(event, "type", None)
            obj = getattr(getattr(event, "data", None), "object", None)
            session_id = getattr(obj, "id", None) if etype == "checkout.session.completed" else None
            pi_id = getattr(obj, "id", None) if etype == "payment_intent.payment_failed" else None
            if etype == "charge.refunded":
                pi_id = getattr(obj, "payment_intent", None) or pi_id

            payment = None
            if session_id:
                payment = (
                    Payment.objects.filter(stripe_checkout_session_id=str(session_id))
                    .order_by("-created_at")
                    .first()
                )
            elif pi_id:
                payment = (
                    Payment.objects.filter(stripe_payment_intent_id=str(pi_id))
                    .order_by("-created_at")
                    .first()
                )

            if payment:
                log_payment_event(
                    payment,
                    "webhook_received",
                    "Stripe webhook received (verified).",
                    metadata={"event_type": str(etype or ""), "event_id": event_id},
                )
        except Exception:
            logger.exception("Failed to log webhook_received PaymentEvent")

        try:
            handle_stripe_event(event)
        except Exception as exc:
            logger.exception(
                "Stripe webhook handler failed event_id=%s event_type=%s",
                event_id,
                getattr(event, "type", ""),
            )
            logger.warning(
                "Stripe will retry this webhook (HTTP 500) event_id=%s type=%s exc=%s",
                event_id,
                event_type,
                type(exc).__name__,
            )
            mark_receipt_failed(receipt, f"{type(exc).__name__}: {exc}")
            return HttpResponse(status=500)

        mark_receipt_processed(receipt)
        return HttpResponse(status=200)


@login_required
def checkout_success_view(request):
    """Browser return after hosted checkout; fulfillment is finalized asynchronously on the server."""
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
    """User cancelled hosted checkout; drop unpaid draft order if present."""
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


@login_required
@never_cache
def refund_request_view(request, order_id: int):
    """
    Customer refund request page.

    This is intentionally customer-only:
    - creates a RefundRequest row with status=pending
    - does not perform admin approval or processor-side refund execution

    ``never_cache`` keeps status in sync after operators approve or process refunds (fresh HTML on each visit).
    """
    try:
        order = Order.objects.prefetch_related("payments").get(id=int(order_id), user=request.user)
    except (Order.DoesNotExist, ValueError, TypeError):
        return redirect("order_list")

    payment = order.payments.order_by("-created_at").first()
    if not payment:
        messages.error(request, "We couldn't find a recorded payment for this order.")
        return redirect("order_detail", pk=order.id)

    refund_open, refund_latest = customer_refund_open_and_latest(payment, request.user)

    paid_like = payment.status in (
        Payment.Status.SUCCEEDED,
        Payment.Status.REFUND_PENDING,
        Payment.Status.PARTIALLY_REFUNDED,
        Payment.Status.REFUNDED,
    )
    if not paid_like and refund_latest is None:
        messages.info(
            request,
            "Refund requests are available after an order is paid.",
        )
        return redirect("order_detail", pk=order.id)

    can_submit_new = payment.status == Payment.Status.SUCCEEDED and refund_open is None

    if request.method == "POST":
        if not can_submit_new:
            if refund_open:
                messages.info(
                    request,
                    "You already have a refund request in progress. The latest status is on this page.",
                )
            else:
                messages.info(
                    request,
                    "A new request isn't available for this order right now.",
                )
            return redirect("payments:refund_request", order_id=order.id)

        reason = (request.POST.get("reason") or "").strip()
        if len(reason) < 10:
            messages.error(
                request,
                "Please share a little more detail (at least 10 characters) so we can understand what happened.",
            )
            return redirect("payments:refund_request", order_id=order.id)

        rr = RefundRequest.objects.create(
            payment=payment,
            user=request.user,
            reason=reason,
            status=RefundRequest.Status.PENDING,
        )
        log_payment_event(
            payment,
            "refund_request_submitted",
            "Customer submitted a refund request.",
            metadata={"refund_request_id": str(rr.id)},
        )
        messages.success(
            request,
            "Your request is submitted. We'll review it and post updates here as soon as there's news.",
        )
        return redirect("payments:refund_request", order_id=order.id)

    return render(
        request,
        "pages/payments/refund_request.html",
        {
            "order": order,
            "payment": payment,
            "refund_request_open": refund_open,
            "refund_request_latest": refund_latest,
            "can_submit_refund_request": can_submit_new,
            "payment_status_summary": build_customer_payment_status_summary(order),
        },
    )


def _is_operator(user) -> bool:
    return bool(getattr(user, "is_staff", False) or getattr(user, "role", "") in {"admin", "producer"})


def _producer_can_act_on_refund(user, rr: RefundRequest) -> tuple[bool, str]:
    """
    Producers can only approve/reject for single-producer orders.

    Rationale: refund requests are payment-level; for multi-vendor orders a single producer
    should not approve/refuse a full refund unilaterally.
    """
    if getattr(user, "role", "") != "producer":
        return False, "Not a producer."
    payment = getattr(rr, "payment", None)
    order = getattr(payment, "order", None) if payment else None
    if not order:
        return False, "Refund request has no linked order."
    producer_ids = set(
        OrderItem.objects.filter(order=order)
        .values_list("product__producer_id", flat=True)
        .distinct()
    )
    if not producer_ids:
        return False, "Order has no items."
    if len(producer_ids) != 1:
        return False, "Multi-vendor order: requires admin review."
    only_pid = next(iter(producer_ids))
    if only_pid != getattr(user, "id", None):
        return False, "This refund request is not for your order."
    return True, ""


@login_required
def refund_inbox_view(request):
    """
    Operator inbox for refund requests.
    - Admins/staff see all.
    - Producers see requests for orders that include their products.
    """
    if not _is_operator(request.user):
        return redirect("home")

    qs = RefundRequest.objects.select_related("payment", "payment__order", "user").order_by("-created_at")

    if getattr(request.user, "role", "") == "producer" and not getattr(request.user, "is_staff", False):
        qs = qs.filter(payment__order__orderitem__product__producer=request.user).distinct()

    status = (request.GET.get("status") or "").strip()
    if status:
        qs = qs.filter(status=status)

    rows = list(qs[:200])
    can_process_refund = bool(
        getattr(request.user, "is_staff", False) or getattr(request.user, "role", "") == "admin"
    )
    return render(
        request,
        "pages/payments/refund_inbox.html",
        {
            "rows": rows,
            "status_filter": status,
            "status_choices": RefundRequest.Status.choices,
            "can_process_refund": can_process_refund,
        },
    )


@login_required
def refund_approve_view(request, refund_request_id: int):
    if request.method != "POST":
        return redirect("payments:refund_inbox")
    if not _is_operator(request.user):
        return redirect("home")

    rr = RefundRequest.objects.select_related("payment", "payment__order").filter(pk=refund_request_id).first()
    if not rr:
        messages.error(request, "Refund request not found.")
        return redirect("payments:refund_inbox")

    if rr.status != RefundRequest.Status.PENDING:
        messages.info(request, "Refund request is not pending.")
        return redirect("payments:refund_inbox")

    if getattr(request.user, "role", "") == "producer" and not getattr(request.user, "is_staff", False):
        ok, why = _producer_can_act_on_refund(request.user, rr)
        if not ok:
            messages.error(request, why or "Not allowed.")
            return redirect("payments:refund_inbox")

    rr.status = RefundRequest.Status.APPROVED
    rr.admin_note = (request.POST.get("note") or rr.admin_note or "").strip()
    rr.save(update_fields=["status", "admin_note"])
    if rr.payment_id:
        log_payment_event(
            rr.payment,
            "refund_request_approved",
            "Refund request approved by operator.",
            metadata={"refund_request_id": str(rr.id)},
        )
    messages.success(request, f"Refund request #{rr.id} approved.")
    return redirect("payments:refund_inbox")


@login_required
def refund_reject_view(request, refund_request_id: int):
    if request.method != "POST":
        return redirect("payments:refund_inbox")
    if not _is_operator(request.user):
        return redirect("home")

    rr = RefundRequest.objects.select_related("payment", "payment__order").filter(pk=refund_request_id).first()
    if not rr:
        messages.error(request, "Refund request not found.")
        return redirect("payments:refund_inbox")

    if rr.status not in (RefundRequest.Status.PENDING, RefundRequest.Status.APPROVED):
        messages.info(request, "This refund request can no longer be rejected from here.")
        return redirect("payments:refund_inbox")

    if getattr(request.user, "role", "") == "producer" and not getattr(request.user, "is_staff", False):
        ok, why = _producer_can_act_on_refund(request.user, rr)
        if not ok:
            messages.error(request, why or "Not allowed.")
            return redirect("payments:refund_inbox")

    rr.status = RefundRequest.Status.REJECTED
    rr.admin_note = (request.POST.get("note") or rr.admin_note or "").strip()
    rr.save(update_fields=["status", "admin_note"])
    if rr.payment_id:
        log_payment_event(
            rr.payment,
            "refund_request_rejected",
            "Refund request rejected by operator.",
            metadata={"refund_request_id": str(rr.id)},
        )
    messages.success(request, f"Refund request #{rr.id} rejected.")
    return redirect("payments:refund_inbox")


@login_required
def refund_process_view(request, refund_request_id: int):
    """
    Run the refund settlement flow (approved, in-flight resume, or failed retry).
    Production safety: staff/admin only.
    """
    if request.method != "POST":
        return redirect("payments:refund_inbox")
    if not (getattr(request.user, "is_staff", False) or getattr(request.user, "role", "") == "admin"):
        messages.error(request, "Only admins can process refunds.")
        return redirect("payments:refund_inbox")

    rr = RefundRequest.objects.select_related("payment", "payment__order").filter(pk=refund_request_id).first()
    if not rr:
        messages.error(request, "Refund request not found.")
        return redirect("payments:refund_inbox")

    if rr.status not in (
        RefundRequest.Status.APPROVED,
        RefundRequest.Status.PROCESSING,
        RefundRequest.Status.FAILED,
    ):
        messages.error(request, "This refund request is not ready to process here.")
        return redirect("payments:refund_inbox")

    try:
        result = process_refund_request(rr.id)
        if result.outcome == "already_processed":
            messages.info(
                request,
                f"Refund request #{rr.id} was already settled. Nothing more was sent to the payment provider.",
            )
        else:
            messages.success(request, f"Refund processed for request #{rr.id}.")
    except ValueError as exc:
        messages.warning(request, str(exc))
    except Exception:
        logger.exception("Refund processing failed refund_request_id=%s", rr.id)
        messages.error(request, "Refund processing failed. Please try again or contact support.")
    return redirect("payments:refund_inbox")


@login_required
def refund_delete_view(request, refund_request_id: int):
    """
    Superuser cleanup: remove pending, rejected, or failed rows without a completed refund.
    Does not change settled payment state beyond deleting the request row.
    """
    if request.method != "POST":
        return redirect("payments:refund_inbox")
    if not getattr(request.user, "is_superuser", False):
        messages.error(request, "Only superusers can delete refund requests.")
        return redirect("payments:refund_inbox")

    rr = RefundRequest.objects.select_related("payment", "payment__order").filter(pk=refund_request_id).first()
    if not rr:
        messages.error(request, "Refund request not found.")
        return redirect("payments:refund_inbox")

    if rr.status not in (
        RefundRequest.Status.PENDING,
        RefundRequest.Status.REJECTED,
        RefundRequest.Status.FAILED,
    ):
        messages.error(request, "Only pending, rejected, or failed requests can be deleted.")
        return redirect("payments:refund_inbox")

    rid = rr.id
    payment = rr.payment
    rr.delete()
    if payment and payment.pk:
        log_payment_event(
            payment,
            "refund_request_deleted",
            f"Refund request #{rid} deleted by superuser.",
            metadata={"refund_request_id": str(rid)},
        )
    messages.success(request, f"Refund request #{rid} was deleted.")
    return redirect("payments:refund_inbox")
