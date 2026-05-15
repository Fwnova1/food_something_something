from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    Stripe Checkout Session + PaymentIntent linkage. Card data never touches this server.

    Refund state is tracked here (``refund_pending`` → ``partially_refunded`` / ``refunded``) so the
    storefront summary stays in sync with settlement, separate from ``RefundRequest`` approval text.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        # Refund lifecycle is intentionally modeled on Payment (not Order) because Stripe refunds
        # are tied to the payment/charge and can be partial.
        REFUND_PENDING = "refund_pending", "Refund pending"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="usd")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    stripe_checkout_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Payment({self.stripe_checkout_session_id!r}, {self.status})"


class RefundRequest(models.Model):
    """
    Customer-initiated refund workflow.

    Architecture note:
    - We store a separate RefundRequest row rather than overloading Payment with "refund_reason/status"
      so that admins have an explicit approval trail (reason/admin_note/processed_at).
    - Stripe refund creation is performed by admins (or future automation) and recorded via
      ``stripe_refund_id``. We use Stripe idempotency keys at call time to prevent double refunds.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="refund_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refund_requests",
    )

    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    admin_note = models.TextField(blank=True)
    stripe_refund_id = models.CharField(max_length=255, blank=True, null=True, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    # Set when status first moves to processing (committed before the gateway refund call).
    processing_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "status"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"RefundRequest(payment_id={self.payment_id}, status={self.status})"


class PaymentEvent(models.Model):
    """
    Append-only audit log for payment lifecycle (internal event types and messages).

    Design notes:
    - Keeping this table append-only (no edits/deletes in normal flows) makes incident review easy.
    - Events are for staff admin, operators, and internal audit tooling — not for customer-facing
      order or payment pages (those use payment/refund status and plain-language summaries only).
    """

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["payment", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"PaymentEvent(payment_id={self.payment_id}, type={self.event_type})"


class StripeWebhookReceipt(models.Model):
    """
    Enterprise reliability primitive: store Stripe webhook event IDs with a UNIQUE constraint.

    Stripe guarantees each webhook delivery includes an immutable event id (evt_...).
    Stripe may deliver the same event multiple times (retries, network timeouts, etc).

    Processing rules (see ``claim_webhook_receipt``):

    - ``event_id`` is UNIQUE — concurrent first deliveries dedupe via ``IntegrityError`` on insert
      (SQLite-friendly; no ``SELECT FOR UPDATE`` on this row).
    - ``processed``: Stripe duplicate deliveries stop here (HTTP 200, handler not re-run).
    - ``failed``: Stripe retries re-enter processing after resetting to ``received``.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        IGNORED = "ignored", "Ignored"

    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    error_message = models.TextField(blank=True)

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"StripeWebhookReceipt({self.event_id}, {self.status})"


class ProducerPayout(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"

    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="producer_payouts",
    )
    week_start = models.DateField(db_index=True)
    week_end = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PAID, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_end", "-created_at"]

    def __str__(self) -> str:
        return f"Payout(producer={self.producer_id}, amount={self.amount}, {self.week_start}..{self.week_end})"


class ProducerPayoutItem(models.Model):
    payout = models.ForeignKey(
        "payments.ProducerPayout",
        on_delete=models.CASCADE,
        related_name="items",
    )
    order_item = models.OneToOneField(
        "orders.OrderItem",
        on_delete=models.CASCADE,
        related_name="payout_item",
    )
    producer_amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]
