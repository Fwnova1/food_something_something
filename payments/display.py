"""
Human-readable payment summaries for templates.

**Customer storefront** (orders, checkout, refund help for shoppers): use only the
``customer_*`` helpers, ``build_customer_payment_history_rows``, ``build_customer_payment_status_summary``,
``customer_receipt_breakdown_for_order``, and template filters in ``payments.templatetags.payments_tags``.
Do not surface Stripe ids, webhook vocabulary, ``PaymentEvent`` types, or raw model status strings in
those UIs.

**Admin / operator / audit**: use ``build_payment_history_rows``, ``stripe_reference_summary``,
``payment_method_label``, Django admin on ``Payment`` / ``PaymentEvent`` / ``StripeWebhookReceipt``,
and the refund inbox views — those layers stay detailed.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from orders.models import Order

from .models import Payment, RefundRequest

_USD_QUANT = Decimal("0.01")

# Customer order page: single friendly label for how the customer paid (no card brand / provider names).
CUSTOMER_FACING_PAYMENT_TYPE_LABEL = "Online payment"


def quantize_money_usd(value) -> Decimal:
    """
    Coerce to Decimal and quantize to two decimal places (half-up).

    Used for all storefront money display (including non-USD symbols in ``format_payment_amount``)
    so amounts always show cents. Display-only; does not alter stored ``Decimal`` rows.
    """
    if value is None or value == "":
        d = Decimal("0")
    elif isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(_USD_QUANT, rounding=ROUND_HALF_UP)


def format_usd(value) -> str:
    """Always ``$16.22`` (two decimal places)."""
    q = quantize_money_usd(value)
    return f"${q:.2f}"


def payment_method_label() -> str:
    """Admin/audit label for how checkout is collected (includes provider name for operators)."""
    return "Card (Stripe Checkout)"


def mask_stripe_reference(value: str, *, tail: int = 14) -> str:
    v = (value or "").strip()
    if not v:
        return "—"
    if len(v) <= tail + 1:
        return v
    return f"…{v[-tail:]}"


def stripe_reference_summary(payment: Payment, *, mask: bool = True) -> str:
    """Short PI + session line for tables (truncated when ``mask``)."""
    pi = (payment.stripe_payment_intent_id or "").strip()
    sess = (payment.stripe_checkout_session_id or "").strip()

    def fmt(chunk: str) -> str:
        if not chunk:
            return "—"
        return mask_stripe_reference(chunk) if mask else chunk

    bits = []
    if pi:
        bits.append(f"PI {fmt(pi)}")
    if sess:
        bits.append(f"Sess {fmt(sess)}")
    return " · ".join(bits) if bits else "—"


def refund_status_for_payment(payment: Payment) -> str:
    """Operator/admin refund column (not customer storefront wording)."""
    st = payment.status
    if st == Payment.Status.REFUNDED:
        return "Refunded"
    if st == Payment.Status.PARTIALLY_REFUNDED:
        return "Partially refunded"
    if st == Payment.Status.REFUND_PENDING:
        return "Refund processing (payment)"

    rr = payment.refund_requests.order_by("-created_at").first()
    if rr:
        if rr.status == RefundRequest.Status.COMPLETED:
            return "Refunded"
        if rr.status == RefundRequest.Status.PROCESSING:
            return "Refund processing (request)"
        if rr.status == RefundRequest.Status.FAILED:
            return "Refund attempt failed"
        if rr.status == RefundRequest.Status.APPROVED:
            return "Approved — not settled yet"
        if rr.status == RefundRequest.Status.PENDING:
            return "Refund requested"
        if rr.status == RefundRequest.Status.REJECTED:
            return "Refund declined"
    return "—"


def customer_refund_activity_for_payment(payment: Payment) -> str:
    """Single refund-activity cell for customer payment tables (no raw status strings)."""
    st = payment.status
    if st == Payment.Status.REFUND_PENDING:
        return "Being processed"
    if st in (Payment.Status.REFUNDED, Payment.Status.PARTIALLY_REFUNDED):
        return customer_payment_status_label(st)

    rr = payment.refund_requests.order_by("-created_at").first()
    if not rr:
        return "—"
    return customer_refund_request_status_label(rr.status)


def format_payment_amount(payment: Payment) -> str:
    """Format stored amount with exactly two fractional digits (``$12.30`` or ``12.30 EUR``)."""
    cur = (payment.currency or "usd").upper()
    q = quantize_money_usd(payment.amount)
    if cur == "USD":
        return f"${q:.2f}"
    return f"{q:.2f} {cur}"


def build_payment_history_rows(order: Order, *, mask_refs: bool = True) -> list[dict]:
    """Operator/admin-oriented rows (includes method + Stripe reference strings)."""
    rows: list[dict] = []
    for p in order.payments.all():
        rows.append(
            {
                "status": p.get_status_display(),
                "amount_display": format_payment_amount(p),
                "method": payment_method_label(),
                "reference": stripe_reference_summary(p, mask=mask_refs),
                "refund": refund_status_for_payment(p),
                "created_at": p.created_at,
                "paid_at": p.paid_at,
                "updated_at": p.updated_at,
            }
        )
    return rows


def customer_payment_status_label(status: str) -> str:
    """Short, marketplace-friendly labels for customer order / refund screens (no DB jargon)."""
    if not status:
        return "—"
    mapping = {
        Payment.Status.PENDING: "Awaiting payment",
        Payment.Status.PROCESSING: "Payment finishing up",
        Payment.Status.SUCCEEDED: "Paid",
        Payment.Status.FAILED: "Payment didn't go through",
        Payment.Status.REFUND_PENDING: "Being processed",
        Payment.Status.PARTIALLY_REFUNDED: "Partly refunded",
        Payment.Status.REFUNDED: "Refunded",
    }
    # Never echo raw model status values to shoppers (could look like debug strings).
    return mapping.get(status, "—")


def customer_refund_request_status_label(status: str) -> str:
    """
    Refund request lifecycle for customers (not internal enum names).

    Intended progression: team review → approval decision → sending the refund → outcome.
    """
    if not status:
        return "—"
    mapping = {
        RefundRequest.Status.PENDING: "Under review",
        RefundRequest.Status.APPROVED: "Refund approved",
        RefundRequest.Status.PROCESSING: "Being processed",
        RefundRequest.Status.REJECTED: "Not approved",
        RefundRequest.Status.COMPLETED: "Refunded",
        RefundRequest.Status.FAILED: "Couldn't complete",
    }
    return mapping.get(status, "—")


_REFUND_OPEN_STATUSES = frozenset(
    {
        RefundRequest.Status.PENDING,
        RefundRequest.Status.APPROVED,
        RefundRequest.Status.PROCESSING,
    }
)


def customer_refund_open_and_latest(payment: Payment | None, user) -> tuple[RefundRequest | None, RefundRequest | None]:
    """
    Return ``(open_request, most_recent_request)`` for this customer on the payment.

    *Open* means still in-flight: pending team review, approved but not yet sent, or actively being processed.
    """
    if not payment or not getattr(user, "is_authenticated", False):
        return None, None
    rows = list(
        RefundRequest.objects.filter(payment_id=payment.pk, user_id=user.pk).order_by("-created_at")
    )
    if not rows:
        return None, None
    latest = rows[0]
    open_rr = next((r for r in rows if r.status in _REFUND_OPEN_STATUSES), None)
    return open_rr, latest


_RECEIPT_AFTER_PAY_STATUSES = frozenset(
    {
        Payment.Status.SUCCEEDED,
        Payment.Status.REFUND_PENDING,
        Payment.Status.PARTIALLY_REFUNDED,
        Payment.Status.REFUNDED,
    }
)


def customer_receipt_breakdown_for_order(order: Order) -> dict[str, Decimal] | None:
    """
    Customer-facing receipt lines (gross, platform fee, producer share) after payment.

    Returns ``None`` until the order has a successful payment in a post-payment state so the breakdown
    reads as a receipt, not a quote. Amounts are quantized USD cents for display with ``|usd``.
    """
    payment = order.payments.order_by("-created_at").first()
    if not payment or payment.status not in _RECEIPT_AFTER_PAY_STATUSES:
        return None
    if not order.orderitem_set.exists():
        return None

    from orders.commission import order_fee_breakdown

    raw = order_fee_breakdown(order)
    item_total = quantize_money_usd(raw.get("gross_amount"))
    platform_fee = quantize_money_usd(raw.get("commission_amount"))
    paid_to_producers = quantize_money_usd(raw.get("producer_amount"))
    if item_total == Decimal("0") and platform_fee == Decimal("0") and paid_to_producers == Decimal("0"):
        return None
    return {
        "item_total": item_total,
        "platform_fee": platform_fee,
        "paid_to_producers": paid_to_producers,
    }


def build_customer_payment_status_summary(order: Order) -> str:
    """
    Short plain-language payment summary for customers.

    Derived only from ``Payment`` / ``RefundRequest`` state — never from ``PaymentEvent`` rows,
    so internal audit names (e.g. ``checkout_started``, ``webhook_received``) are not surfaced.
    """
    payments = list(order.payments.order_by("-created_at"))
    if not payments:
        return "We don't have a payment on file for this order yet."

    payment = payments[0]
    st = payment.status

    if st == Payment.Status.PENDING:
        msg = "This order still needs payment. When you're ready, complete checkout from your cart or order."
    elif st == Payment.Status.PROCESSING:
        msg = "Your payment is almost done. This page will refresh as soon as it clears."
    elif st == Payment.Status.FAILED:
        msg = "That payment didn't go through. You can try again from your cart."
    elif st == Payment.Status.REFUND_PENDING:
        msg = "Your refund is being processed. We'll update this page when it's finished."
    elif st == Payment.Status.PARTIALLY_REFUNDED:
        msg = "Part of your order has been refunded."
    elif st == Payment.Status.REFUNDED:
        msg = "This order has been fully refunded."
    else:
        msg = "Your order is paid."
        extra = customer_refund_activity_for_payment(payment)
        if extra and extra != "—":
            # Em dash keeps this readable as one sentence (not a debug key/value pair).
            msg = f"{msg} Refund update — {extra}."

    if len(payments) > 1:
        msg = f"{msg} Older payments for this order appear in the table below."

    return msg


def build_customer_payment_history_rows(order: Order) -> list[dict]:
    """
    Customer order page — one row per ``Payment``.

    Shown in the UI: status, amount, refund activity, started, paid time only.
    No Stripe IDs, session/PI text, or provider-specific method strings; payment type
    is described once in the section copy as ``CUSTOMER_FACING_PAYMENT_TYPE_LABEL``.
    """
    rows: list[dict] = []
    for p in order.payments.all():
        rows.append(
            {
                "status": customer_payment_status_label(p.status),
                "amount_display": format_payment_amount(p),
                "refund": customer_refund_activity_for_payment(p),
                "created_at": p.created_at,
                "paid_at": p.paid_at,
            }
        )
    return rows


def summarize_payment_for_order(order: Order) -> str:
    """Return ``paid``, ``pending``, ``failed``, ``refund_pending``, ``partially_refunded``, ``refunded``, or ``unknown``."""
    payment = order.payments.order_by("-created_at").first()
    if not payment:
        return "unknown"

    status = payment.status
    if status == Payment.Status.SUCCEEDED:
        return "paid"
    if status in (Payment.Status.PENDING, Payment.Status.PROCESSING):
        return "pending"
    if status == Payment.Status.FAILED:
        return "failed"
    if status == Payment.Status.REFUND_PENDING:
        return "refund_pending"
    if status == Payment.Status.PARTIALLY_REFUNDED:
        return "partially_refunded"
    if status == Payment.Status.REFUNDED:
        return "refunded"
    return "unknown"


def payment_status_label(slug: str) -> str:
    mapping = {
        "paid": "Paid",
        "pending": "Awaiting payment",
        "failed": "Payment didn't go through",
        "refund_pending": "Being processed",
        "partially_refunded": "Partly refunded",
        "refunded": "Refunded",
        "unknown": "—",
    }
    return mapping.get(slug, "—")
