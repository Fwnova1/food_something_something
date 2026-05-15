from django.contrib import admin
from django.db.models import Prefetch, Sum

from brfn.admin_actions import AdminActionSelectLabelMixin

from payments.display import (
    format_payment_amount,
    payment_method_label,
    refund_status_for_payment,
    stripe_reference_summary,
)
from payments.models import Payment

from .models import Order, OrderItem


class PaymentInline(admin.TabularInline):
    model = Payment
    fk_name = "order"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        "status",
        "amount_currency_inline",
        "method_inline",
        "stripe_ref_inline",
        "refund_inline",
        "paid_at",
        "created_at",
    )
    readonly_fields = fields

    def amount_currency_inline(self, obj):
        return format_payment_amount(obj)

    amount_currency_inline.short_description = "Amount"

    def method_inline(self, obj):
        return payment_method_label()

    method_inline.short_description = "Method"

    def stripe_ref_inline(self, obj):
        return stripe_reference_summary(obj, mask=False)

    stripe_ref_inline.short_description = "Stripe ref"

    def refund_inline(self, obj):
        return refund_status_for_payment(obj)

    refund_inline.short_description = "Refund"


@admin.register(OrderItem)
class OrderItemAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "product",
        "quantity",
        "price",
        "gross_amount",
        "commission_amount",
        "producer_amount",
    )
    list_filter = ("order__created_at", "product__producer")
    search_fields = ("order__id", "product__name", "product__producer__username")


@admin.register(Order)
class OrderAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = ("id", "user", "created_at", "status", "total", "platform_fee_total", "producer_total")
    list_filter = ("status", "created_at")
    search_fields = ("id", "user__username", "user__email")
    inlines = (PaymentInline,)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related(
            Prefetch(
                "payments",
                queryset=Payment.objects.prefetch_related("refund_requests").order_by("-created_at"),
            )
        )

    def platform_fee_total(self, obj: Order):
        val = obj.orderitem_set.aggregate(s=Sum("commission_amount"))["s"] or 0
        return val

    def producer_total(self, obj: Order):
        val = obj.orderitem_set.aggregate(s=Sum("producer_amount"))["s"] or 0
        return val

    platform_fee_total.short_description = "Platform fee"
    producer_total.short_description = "Producer total"
