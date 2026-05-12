"""Django admin for payments: detailed audit fields, Stripe references, and bulk actions.

Storefront customer pages must not reuse these layouts; they use ``payments.display`` /
``payments_tags`` customer helpers instead.
"""

from decimal import Decimal

from django.contrib import admin
from django.contrib import messages
from django.db import models
from django.db.models import Count, Sum
from django.template.response import TemplateResponse
from django.urls import path
import logging

from brfn.admin_actions import AdminActionSelectLabelMixin

from .models import Payment, PaymentEvent, StripeWebhookReceipt, RefundRequest
from orders.commission import platform_revenue_summary
from .display import (
    format_payment_amount,
    payment_method_label,
    refund_status_for_payment,
    stripe_reference_summary,
)
from .events import log_payment_event
from .refund_service import process_refund_request

logger = logging.getLogger(__name__)


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    can_delete = False
    fields = ("created_at", "event_type", "message")
    readonly_fields = ("created_at", "event_type", "message")
    ordering = ("created_at", "id")


@admin.register(Payment)
class PaymentAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "order",
        "status",
        "amount_currency_admin",
        "method_admin",
        "stripe_ref_admin",
        "refund_admin",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("stripe_checkout_session_id", "stripe_payment_intent_id", "user__email", "user__username")
    readonly_fields = (
        "created_at",
        "updated_at",
        "paid_at",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
        "method_admin",
        "refund_admin",
        "stripe_ref_admin",
    )
    fieldsets = (
        (None, {"fields": ("user", "order", "status", "amount", "currency", "metadata")}),
        ("Stripe", {"fields": ("stripe_checkout_session_id", "stripe_payment_intent_id", "stripe_ref_admin")}),
        ("Summary", {"fields": ("method_admin", "refund_admin")}),
        ("Timestamps", {"fields": ("paid_at", "created_at", "updated_at")}),
    )
    inlines = (PaymentEventInline,)

    def amount_currency_admin(self, obj: Payment) -> str:
        return format_payment_amount(obj)

    amount_currency_admin.short_description = "Amount"

    def method_admin(self, obj: Payment) -> str:
        return payment_method_label()

    method_admin.short_description = "Method"

    def stripe_ref_admin(self, obj: Payment) -> str:
        return stripe_reference_summary(obj, mask=False)

    stripe_ref_admin.short_description = "Stripe reference"

    def refund_admin(self, obj: Payment) -> str:
        return refund_status_for_payment(obj)

    refund_admin.short_description = "Refund"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("user", "order").prefetch_related("refund_requests")


@admin.action(description="Approve refund requests (submitted → approved, not a payout)")
def approve_refund_requests(modeladmin, request, queryset):
    updated = 0
    for rr in queryset.select_related("payment").order_by("id"):
        if rr.status != RefundRequest.Status.PENDING:
            continue
        changed = RefundRequest.objects.filter(
            pk=rr.pk,
            status=RefundRequest.Status.PENDING,
        ).update(status=RefundRequest.Status.APPROVED)
        if not changed:
            continue
        updated += 1
        payment = rr.payment
        if payment and payment.pk:
            log_payment_event(
                payment,
                "refund_request_approved",
                "Refund request approved via Django admin bulk action.",
                metadata={"refund_request_id": str(rr.pk), "source": "admin_refund_bulk"},
            )
    modeladmin.message_user(request, f"Approved {updated} refund request(s).")


@admin.action(description="Reject refund requests (submitted or approved)")
def reject_refund_requests(modeladmin, request, queryset):
    updated = 0
    for rr in queryset.select_related("payment").order_by("id"):
        if rr.status not in (
            RefundRequest.Status.PENDING,
            RefundRequest.Status.APPROVED,
        ):
            continue
        changed = RefundRequest.objects.filter(
            pk=rr.pk,
            status__in=(
                RefundRequest.Status.PENDING,
                RefundRequest.Status.APPROVED,
            ),
        ).update(status=RefundRequest.Status.REJECTED)
        if not changed:
            continue
        updated += 1
        payment = rr.payment
        if payment and payment.pk:
            log_payment_event(
                payment,
                "refund_request_rejected",
                "Refund request rejected via Django admin bulk action.",
                metadata={"refund_request_id": str(rr.pk), "source": "admin_refund_bulk"},
            )
    modeladmin.message_user(request, f"Rejected {updated} refund request(s).")


@admin.action(
    description="Execute refund with payment provider (sends money; only approved or failed-retry)",
)
def process_approved_refund_requests(modeladmin, request, queryset):
    """
    Calls ``process_refund_request`` only for **approved** or **failed** rows.

    **Processing** and **completed** rows are skipped so operators do not re-run a settlement
    that is already in flight or finished. Audit events are still emitted inside the service
    when execution runs.
    """
    ok = 0
    idempotent = 0
    skipped_completed = 0
    skipped_in_progress = 0
    skipped_ineligible = 0
    failed = 0
    for rr in queryset.select_related("payment").order_by("id"):
        if rr.status == RefundRequest.Status.COMPLETED:
            skipped_completed += 1
            continue
        if rr.status == RefundRequest.Status.PROCESSING:
            skipped_in_progress += 1
            continue
        if rr.status not in (RefundRequest.Status.APPROVED, RefundRequest.Status.FAILED):
            skipped_ineligible += 1
            continue
        try:
            result = process_refund_request(rr.id)
            if result.outcome == "already_processed":
                idempotent += 1
            else:
                ok += 1
        except ValueError as exc:
            skipped_ineligible += 1
            modeladmin.message_user(
                request,
                f"RefundRequest #{rr.id}: {exc}",
                level=messages.WARNING,
            )
        except Exception:
            failed += 1
            logger.exception("RefundRequest process failed refund_request_id=%s", rr.id)
            modeladmin.message_user(
                request,
                f"RefundRequest #{rr.id} failed to process.",
                level=messages.ERROR,
            )
    modeladmin.message_user(
        request,
        "Refund execution summary — "
        f"new: {ok}, reconciled (already settled): {idempotent}, "
        f"skipped (completed): {skipped_completed}, "
        f"skipped (already running): {skipped_in_progress}, "
        f"skipped (other / validation): {skipped_ineligible}, "
        f"errors: {failed}.",
    )


@admin.action(
    description="Delete refund requests for cleanup (pending, rejected, or failed — superuser only)",
    permissions=["delete"],
)
def delete_refund_requests_action(modeladmin, request, queryset):
    """
    Superuser cleanup only: pending, rejected, or failed rows without a completed refund.
    """
    if not request.user.is_superuser:
        modeladmin.message_user(
            request,
            "Only superusers can delete refund requests.",
            level=messages.ERROR,
        )
        return
    deletable = queryset.filter(
        status__in=(
            RefundRequest.Status.PENDING,
            RefundRequest.Status.REJECTED,
            RefundRequest.Status.FAILED,
        )
    )
    skipped = queryset.count() - deletable.count()
    deleted_count, _ = deletable.delete()
    parts = [f"Deleted {deleted_count} refund request(s)."]
    if skipped:
        parts.append(f"Skipped {skipped} (only pending, rejected, or failed rows can be deleted).")
    modeladmin.message_user(request, " ".join(parts))


@admin.register(RefundRequest)
class RefundRequestAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    """
    Refund queue in Django admin: list + bulk approve/reject/execute/delete.

    Per-row settlement still happens through ``process_refund_request`` (same as the operator inbox).
    """

    list_display = (
        "id",
        "user",
        "payment",
        "refund_reason_preview",
        "status",
        "created_at",
        "processed_at",
    )
    list_select_related = ("user", "payment", "payment__order")
    list_filter = ("status", "created_at", "processed_at")
    search_fields = (
        "id",
        "user__email",
        "user__username",
        "reason",
        "admin_note",
        "payment__stripe_payment_intent_id",
        "payment__stripe_checkout_session_id",
    )
    readonly_fields = (
        "user",
        "payment",
        "reason",
        "created_at",
        "processing_started_at",
        "processed_at",
        "stripe_refund_id",
    )
    fieldsets = (
        (None, {"fields": ("user", "payment", "status", "reason")}),
        ("Operator notes", {"fields": ("admin_note",), "classes": ("wide",)}),
        ("Outcome", {"fields": ("processing_started_at", "processed_at", "stripe_refund_id")}),
        ("Timestamps", {"fields": ("created_at",)}),
    )
    actions = (
        approve_refund_requests,
        reject_refund_requests,
        process_approved_refund_requests,
        delete_refund_requests_action,
    )

    @admin.display(description="Reason (preview)")
    def refund_reason_preview(self, obj: RefundRequest) -> str:
        text = (obj.reason or "").strip().replace("\n", " ")
        if not text:
            return "—"
        return text[:72] + ("…" if len(text) > 72 else "")

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Prefer the scoped "Delete" action above; the stock action can remove any row including completed.
        actions.pop("delete_selected", None)
        if not request.user.is_superuser:
            actions.pop("delete_refund_requests_action", None)
        return actions


def _payments_analytics_view(request):
    """
    Lightweight admin analytics dashboard (university-demo friendly).

    No external dashboard frameworks; we render simple KPI cards + a tiny CSS bar chart + tables.
    """
    status = (request.GET.get("status") or "").strip()
    payments = Payment.objects.all().select_related("user", "order")
    if status:
        payments = payments.filter(status=status)

    totals = Payment.objects.aggregate(
        successful_payments=Count("id", filter=models.Q(status=Payment.Status.SUCCEEDED)),
        failed_payments=Count("id", filter=models.Q(status=Payment.Status.FAILED)),
        refund_pending_payments=Count("id", filter=models.Q(status=Payment.Status.REFUND_PENDING)),
        refunded_payments=Count("id", filter=models.Q(status=Payment.Status.REFUNDED)),
        partially_refunded_payments=Count("id", filter=models.Q(status=Payment.Status.PARTIALLY_REFUNDED)),
        total_revenue=Sum("amount", filter=models.Q(status=Payment.Status.SUCCEEDED)),
        refunded_total=Sum("amount", filter=models.Q(status=Payment.Status.REFUNDED)),
    )

    # Commission/Earnings are derived from OrderItems (demo reporting; no live payout integration).
    platform_summary = platform_revenue_summary()

    # Status distribution for a tiny "chart"
    status_counts = (
        payments.values("status")
        .annotate(c=Count("id"))
        .order_by("-c")
    )
    max_count = max([row["c"] for row in status_counts], default=0) or 1
    chart_rows = [
        {
            "status": row["status"],
            "count": row["c"],
            "pct": int((row["c"] / max_count) * 100),
        }
        for row in status_counts
    ]

    recent = payments.order_by("-created_at")[:25]

    ctx = {
        **admin.site.each_context(request),
        "title": "Payment Analytics",
        "status_filter": status,
        "status_choices": Payment.Status.choices,
        "kpis": {
            "total_revenue": totals.get("total_revenue") or Decimal("0.00"),
            "refunded_total": totals.get("refunded_total") or Decimal("0.00"),
            "successful_payments": totals.get("successful_payments") or 0,
            "failed_payments": totals.get("failed_payments") or 0,
            "refund_pending_payments": totals.get("refund_pending_payments") or 0,
            "refunded_payments": totals.get("refunded_payments") or 0,
            "partially_refunded_payments": totals.get("partially_refunded_payments") or 0,
            "producer_earnings": platform_summary.get("producer_amount") or Decimal("0.00"),
            "platform_commissions": platform_summary.get("commission_amount") or Decimal("0.00"),
        },
        "chart_rows": chart_rows,
        "recent": recent,
    }
    return TemplateResponse(request, "admin/payments/analytics.html", ctx)


def _append_analytics_url(urls):
    return [
        path("analytics/", admin.site.admin_view(_payments_analytics_view), name="payments_analytics"),
        *urls,
    ]


admin.site.get_urls = (lambda orig_get_urls=admin.site.get_urls: (lambda: _append_analytics_url(orig_get_urls())))()


@admin.register(PaymentEvent)
class PaymentEventAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = ("id", "payment", "event_type", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("payment__stripe_checkout_session_id", "payment__stripe_payment_intent_id", "message")
    readonly_fields = ("payment", "event_type", "message", "metadata", "created_at")


@admin.register(StripeWebhookReceipt)
class StripeWebhookReceiptAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = ("event_id", "event_type", "status", "received_at", "processed_at")
    list_filter = ("status", "event_type", "received_at")
    search_fields = ("event_id", "event_type", "error_message")
    readonly_fields = ("event_id", "event_type", "status", "error_message", "received_at", "processed_at")
