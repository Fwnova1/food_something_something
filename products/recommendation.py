from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Avg, Count, Max, Sum
from django.utils import timezone

from orders.models import OrderItem
from products.models import Product


@dataclass
class RecommendationItem:
    product: Product
    score: float
    reason: str


@dataclass
class QuickReorderItem:
    product: Product
    suggested_quantity: int
    reason: str


def _normalize(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return float(value) / float(max_value)


def build_customer_recommendations(user, limit: int = 8) -> list[RecommendationItem]:
    """
    Hybrid recommendation:
    - personal history (frequency, quantity, recency)
    - co-purchase patterns
    - trending fallback (for cold-start users)
    """
    now = timezone.now()
    recent_cutoff = now - timedelta(days=45)

    user_history = list(
        OrderItem.objects.filter(order__user=user)
        .values("product_id")
        .annotate(
            total_qty=Sum("quantity"),
            order_count=Count("order_id", distinct=True),
            last_bought=Max("order__created_at"),
        )
        .order_by("-total_qty")
    )

    purchased_ids = {row["product_id"] for row in user_history}
    scores: dict[int, float] = {}
    reasons: dict[int, str] = {}

    if user_history:
        max_qty = max(row["total_qty"] or 0 for row in user_history) or 1
        max_order_count = max(row["order_count"] or 0 for row in user_history) or 1

        for row in user_history:
            product_id = row["product_id"]
            qty_score = _normalize(row["total_qty"] or 0, max_qty)
            freq_score = _normalize(row["order_count"] or 0, max_order_count)
            recency_score = 1.0 if (row["last_bought"] and row["last_bought"] >= recent_cutoff) else 0.35

            personal_score = (0.5 * qty_score) + (0.35 * freq_score) + (0.15 * recency_score)
            scores[product_id] = scores.get(product_id, 0.0) + personal_score
            reasons[product_id] = "You often buy this product."

        top_user_products = [row["product_id"] for row in user_history[:5]]
        co_purchase_rows = list(
            OrderItem.objects.filter(order__orderitem__product_id__in=top_user_products)
            .exclude(product_id__in=purchased_ids)
            .values("product_id")
            .annotate(co_count=Count("order_id", distinct=True))
            .order_by("-co_count")[: (limit * 3)]
        )

        if co_purchase_rows:
            max_co_count = max(row["co_count"] for row in co_purchase_rows) or 1
            for row in co_purchase_rows:
                product_id = row["product_id"]
                co_score = 0.45 * _normalize(row["co_count"], max_co_count)
                scores[product_id] = scores.get(product_id, 0.0) + co_score
                reasons.setdefault(product_id, "Often bought together with your usual items.")

    trending_rows = list(
        OrderItem.objects.filter(order__created_at__gte=now - timedelta(days=30))
        .values("product_id")
        .annotate(popularity=Sum("quantity"))
        .order_by("-popularity")[: (limit * 3)]
    )
    if trending_rows:
        max_popularity = max(row["popularity"] or 0 for row in trending_rows) or 1
        for row in trending_rows:
            product_id = row["product_id"]
            trending_score = 0.3 * _normalize(row["popularity"] or 0, max_popularity)
            scores[product_id] = scores.get(product_id, 0.0) + trending_score
            reasons.setdefault(product_id, "Popular with the Bristol network this month.")

    if not scores:
        return []

    ranked_product_ids = [pid for pid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
    products_by_id = Product.objects.in_bulk(ranked_product_ids)

    recommendations: list[RecommendationItem] = []
    for pid in ranked_product_ids:
        product = products_by_id.get(pid)
        if not product:
            continue
        recommendations.append(
            RecommendationItem(
                product=product,
                score=scores[pid],
                reason=reasons.get(pid, "Recommended for you."),
            )
        )
    return recommendations


def build_quick_reorder_suggestions(user, limit: int = 4) -> list[QuickReorderItem]:
    """
    Returns products the customer tends to re-order, with a suggested quantity.
    """
    rows = list(
        OrderItem.objects.filter(order__user=user)
        .values("product_id")
        .annotate(
            total_qty=Sum("quantity"),
            order_count=Count("order_id", distinct=True),
            last_bought=Max("order__created_at"),
            avg_quantity=Avg("quantity"),
        )
        .order_by("-last_bought", "-order_count", "-total_qty")[:limit]
    )
    if not rows:
        return []

    products_by_id = Product.objects.in_bulk([row["product_id"] for row in rows])
    suggestions: list[QuickReorderItem] = []
    for row in rows:
        product = products_by_id.get(row["product_id"])
        if not product:
            continue
        avg_qty = row.get("avg_quantity")
        suggested_qty = max(1, round(float(avg_qty))) if avg_qty is not None else 1
        suggestions.append(
            QuickReorderItem(
                product=product,
                suggested_quantity=suggested_qty,
                reason=f"Re-ordered {row['order_count']} times.",
            )
        )
    return suggestions


def get_suggested_quantity_for_product(user, product_id: int) -> int:
    result = OrderItem.objects.filter(order__user=user, product_id=product_id).aggregate(
        avg_quantity=Avg("quantity")
    )
    avg_quantity = result.get("avg_quantity")
    if avg_quantity is None:
        return 1
    return max(1, round(float(avg_quantity)))
