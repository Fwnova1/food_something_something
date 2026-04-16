from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

from django.utils import timezone

from orders.models import OrderItem
from products.models import Product


@dataclass
class DemandForecastItem:
    product: Product
    weekly_demand: list[int]
    forecast_next_week: int
    recommended_stock: int
    trend: str
    confidence: str
    explanation: str


def _week_start(dt):
    d = dt.date()
    return d - timedelta(days=d.weekday())


def _build_recent_weeks(weeks: int) -> list:
    start_of_this_week = _week_start(timezone.now())
    return [start_of_this_week - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]


def _weighted_moving_average(values: list[int]) -> float:
    if not values:
        return 0.0
    weights = list(range(1, len(values) + 1))
    weighted_sum = sum(w * v for w, v in zip(weights, values))
    return weighted_sum / sum(weights)


def build_demand_forecast_for_scope(user, weeks: int = 8, limit: int = 12) -> list[DemandForecastItem]:
    """
    Producer: forecast only own products.
    Admin: forecast across all products.
    """
    week_keys = _build_recent_weeks(weeks)
    min_datetime = timezone.make_aware(datetime.combine(week_keys[0], datetime.min.time()))

    base_qs = OrderItem.objects.filter(order__created_at__gte=min_datetime).select_related("product")
    if user.role == "producer":
        base_qs = base_qs.filter(product__producer=user)

    totals_by_product_week: dict[int, dict] = {}
    product_ids: set[int] = set()

    for item in base_qs:
        pid = item.product_id
        w = _week_start(item.order.created_at)
        if w not in week_keys:
            continue
        product_ids.add(pid)
        product_map = totals_by_product_week.setdefault(pid, {})
        product_map[w] = product_map.get(w, 0) + int(item.quantity)

    if not product_ids:
        return []

    products_by_id = Product.objects.in_bulk(product_ids)
    forecast_items: list[DemandForecastItem] = []

    for pid, week_map in totals_by_product_week.items():
        product = products_by_id.get(pid)
        if not product:
            continue

        weekly_values = [week_map.get(w, 0) for w in week_keys]
        forecast = max(1, round(_weighted_moving_average(weekly_values)))
        recommended_stock = max(1, ceil(forecast * 1.2))

        recent_avg = sum(weekly_values[-3:]) / 3 if len(weekly_values) >= 3 else sum(weekly_values) / max(1, len(weekly_values))
        previous_slice = weekly_values[-6:-3] if len(weekly_values) >= 6 else weekly_values[:-3]
        previous_avg = sum(previous_slice) / len(previous_slice) if previous_slice else recent_avg

        if recent_avg > previous_avg * 1.15:
            trend = "rising"
        elif recent_avg < previous_avg * 0.85:
            trend = "falling"
        else:
            trend = "stable"

        total_units = sum(weekly_values)
        if total_units >= 25:
            confidence = "high"
        elif total_units >= 10:
            confidence = "medium"
        else:
            confidence = "low"

        explanation = (
            f"Forecast uses {weeks}-week weighted demand history. "
            f"Recent trend is {trend}, recommended stock includes 20% safety buffer."
        )

        forecast_items.append(
            DemandForecastItem(
                product=product,
                weekly_demand=weekly_values,
                forecast_next_week=forecast,
                recommended_stock=recommended_stock,
                trend=trend,
                confidence=confidence,
                explanation=explanation,
            )
        )

    forecast_items.sort(key=lambda x: x.forecast_next_week, reverse=True)
    return forecast_items[:limit]
