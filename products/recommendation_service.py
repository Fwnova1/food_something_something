from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product


class RecommendationService:
    def __init__(self) -> None:
        self.endpoint = (
            getattr(settings, "RECOMMENDATION_API_URL", "")
            or getattr(settings, "QUALITY_MODEL_API_URL", "").replace("/predict", "/recommend")
        ).strip()
        self.timeout_seconds = int(getattr(settings, "RECOMMENDATION_API_TIMEOUT_SECONDS", 20))
        self.api_key = (getattr(settings, "RECOMMENDATION_API_KEY", "") or "").strip()
        self.auth_header_name = (
            getattr(settings, "RECOMMENDATION_AUTH_HEADER", getattr(settings, "QUALITY_MODEL_AUTH_HEADER", "X-API-Key"))
            or "X-API-Key"
        ).strip()
        self.default_top_n = int(getattr(settings, "RECOMMENDATION_TOP_N", 5))

    def _available_products(self) -> list[Product]:
        today = timezone.localdate()
        queryset = (
            Product.objects.exclude(availability="unavailable")
            .filter(stock_quantity__gt=0)
            .select_related("category", "producer")
        )
        queryset = queryset.filter(
            Q(availability="year_round")
            | Q(availability="in_season", seasonal_start__isnull=True, seasonal_end__isnull=True)
            | Q(
                availability="in_season",
                seasonal_start__isnull=False,
                seasonal_end__isnull=False,
                seasonal_start__lte=today,
                seasonal_end__gte=today,
            )
        )
        return list(queryset.order_by("-created_at")[:500])

    def _extract_feature_rows(self, user, candidates: list[Product]) -> list[dict]:
        user_orders = list(
            Order.objects.filter(user=user).order_by("created_at").values("id", "created_at")
        )
        order_ids = [int(row["id"]) for row in user_orders]
        user_total_orders_global = float(len(order_ids))

        user_order_items = list(
            OrderItem.objects.filter(order__user=user)
            .select_related("order")
            .order_by("order_id", "id")
            .values("order_id", "product_id", "quantity", "order__created_at")
        )

        product_popularity_rows = (
            OrderItem.objects.values("product_id")
            .annotate(product_popularity=Count("id"))
            .order_by()
        )
        product_popularity_map = {
            int(row["product_id"]): float(row["product_popularity"] or 0.0)
            for row in product_popularity_rows
        }

        product_positions: dict[int, list[float]] = defaultdict(list)
        product_total_quantity: dict[int, float] = defaultdict(float)
        current_order_id = None
        current_position = 0
        for row in user_order_items:
            oid = int(row["order_id"])
            pid = int(row["product_id"])
            qty = float(row.get("quantity") or 0.0)
            if oid != current_order_id:
                current_order_id = oid
                current_position = 1
            else:
                current_position += 1
            product_positions[pid].append(float(current_position))
            product_total_quantity[pid] += qty

        order_dates: list[datetime] = [row["created_at"] for row in user_orders if row.get("created_at")]
        avg_days_between_orders = 0.0
        if len(order_dates) > 1:
            gaps = []
            for idx in range(1, len(order_dates)):
                gap = (order_dates[idx] - order_dates[idx - 1]).days
                gaps.append(float(max(0, gap)))
            avg_days_between_orders = (sum(gaps) / len(gaps)) if gaps else 0.01

        rows: list[dict] = []
        for product in candidates:
            positions = product_positions.get(product.id, [])
            avg_cart_position = (sum(positions) / len(positions)) if positions else 0.0
            user_total_orders = float(product_total_quantity.get(product.id, 0.0))
            rows.append(
                {
                    "product_id": int(product.id),
                    "product_name": product.name,
                    "avg_cart_position": float(avg_cart_position),
                    "avg_days_between_orders": float(avg_days_between_orders),
                    "product_popularity": float(product_popularity_map.get(product.id, 0.0)),
                    "user_total_orders": float(user_total_orders),
                    "user_total_orders_global": float(user_total_orders_global),
                }
            )
        return rows

    def recommend_for_user(self, user, top_n: int | None = None, exclude_recent_days: int = 0) -> dict:
        if not self.endpoint:
            raise RuntimeError("RECOMMENDATION_API_URL is not configured.")

        top_k = max(1, min(int(top_n or self.default_top_n), 20))
        candidates = self._available_products()
        feature_rows = self._extract_feature_rows(user, candidates)
        payload = {"user_id": int(user.id), "top_k": top_k, "candidates": feature_rows}
        body = json.dumps(payload).encode("utf-8")

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers[self.auth_header_name] = self.api_key

        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Recommendation API HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Recommendation API is unreachable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Recommendation API returned invalid JSON.") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("Recommendation API response must be a JSON object.")

        rows = parsed.get("recommendations", [])
        normalized_rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            score = row.get("probability", row.get("score", 0.0))
            try:
                probability = float(score)
            except (TypeError, ValueError):
                probability = 0.0
            if probability > 1.0:
                probability = min(1.0, probability / 100.0)
            probability = max(0.0, min(1.0, probability))
            normalized_rows.append(
                {
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name", ""),
                    "probability": round(probability, 6),
                    "reason": row.get("reason", "Recommended for you."),
                    "explanation": row.get("explanation", ""),
                    "xai_top_features": row.get("xai_top_features", []),
                }
            )

        return {"user_id": parsed.get("user_id", user.id), "recommendations": normalized_rows}


_service_singleton: RecommendationService | None = None


def get_recommendation_service() -> RecommendationService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = RecommendationService()
    return _service_singleton
