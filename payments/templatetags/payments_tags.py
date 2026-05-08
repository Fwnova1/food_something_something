"""Template helpers for payment status badges."""

from django import template

from payments.display import payment_status_label, summarize_payment_for_order

register = template.Library()


@register.filter
def order_payment_status(order):
    return summarize_payment_for_order(order)


@register.filter
def payment_status_display(slug: str) -> str:
    return payment_status_label(slug)
