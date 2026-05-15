"""
Marketplace commission helpers (internal settlement simulation).

Aggregates here feed **customer receipt lines** only through ``payments.display.customer_receipt_breakdown_for_order``
(friendly labels in templates). Admin analytics and reporting use this module directly with full field names.

Scope:
- Commission rate is 5% across all items.
- We do NOT implement Stripe Connect payouts; we only compute and display settlement numbers.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from .models import Order, OrderItem


def order_fee_breakdown(order: Order) -> dict[str, Decimal]:
    """
    Returns a breakdown for the full order:
    - gross_amount: sum of item gross
    - commission_amount: platform fee (5%)
    - producer_amount: total producer earnings (95%)
    """
    agg = OrderItem.objects.filter(order=order).aggregate(
        gross_amount=Sum("gross_amount"),
        commission_amount=Sum("commission_amount"),
        producer_amount=Sum("producer_amount"),
    )
    return {
        "gross_amount": agg["gross_amount"] or Decimal("0.00"),
        "commission_amount": agg["commission_amount"] or Decimal("0.00"),
        "producer_amount": agg["producer_amount"] or Decimal("0.00"),
    }


def producer_earnings_summary(*, producer_user_id: int, since=None, until=None) -> dict[str, Decimal]:
    """
    Sum producer earnings across all order items belonging to the producer.
    Optional date range filters are applied via the parent Order's created_at.
    """
    qs = OrderItem.objects.filter(product__producer_id=producer_user_id).select_related("order")
    if since is not None:
        qs = qs.filter(order__created_at__gte=since)
    if until is not None:
        qs = qs.filter(order__created_at__lte=until)
    agg = qs.aggregate(
        gross_amount=Sum("gross_amount"),
        producer_amount=Sum("producer_amount"),
        commission_amount=Sum("commission_amount"),
    )
    return {
        "gross_amount": agg["gross_amount"] or Decimal("0.00"),
        "producer_amount": agg["producer_amount"] or Decimal("0.00"),
        "commission_amount": agg["commission_amount"] or Decimal("0.00"),
    }


def platform_revenue_summary(*, since=None, until=None) -> dict[str, Decimal]:
    """
    Sum platform revenue (commission) across all order items.
    """
    qs = OrderItem.objects.all().select_related("order")
    if since is not None:
        qs = qs.filter(order__created_at__gte=since)
    if until is not None:
        qs = qs.filter(order__created_at__lte=until)
    agg = qs.aggregate(
        gross_amount=Sum("gross_amount"),
        commission_amount=Sum("commission_amount"),
        producer_amount=Sum("producer_amount"),
    )
    return {
        "gross_amount": agg["gross_amount"] or Decimal("0.00"),
        "commission_amount": agg["commission_amount"] or Decimal("0.00"),
        "producer_amount": agg["producer_amount"] or Decimal("0.00"),
    }


def per_producer_breakdown_for_order(order: Order):
    """
    Returns rows grouped per producer for displaying on receipts/admin.
    """
    rows = defaultdict(lambda: {"gross": Decimal("0.00"), "commission": Decimal("0.00"), "producer": Decimal("0.00")})
    for item in OrderItem.objects.filter(order=order).select_related("product__producer"):
        pid = item.product.producer_id
        rows[pid]["gross"] += item.gross_amount
        rows[pid]["commission"] += item.commission_amount
        rows[pid]["producer"] += item.producer_amount
    return rows

