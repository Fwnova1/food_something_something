from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "order",
        "amount",
        "currency",
        "status",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("stripe_checkout_session_id", "stripe_payment_intent_id", "user__email", "user__username")
    readonly_fields = ("created_at", "updated_at", "paid_at")
