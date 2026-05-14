from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from decimal import Decimal

from .forecasting import build_demand_forecast_for_scope
from .models import Category, Product
from orders.models import OrderItem
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter
from .recommendation import build_customer_recommendations, build_quick_reorder_suggestions
from sustainability.services import calculate_postcode_distance
from .serializers import (
    CategorySerializer,
    DemandForecastItemSerializer,
    FoodMilesItemSerializer,
    ProductSerializer,
    QuickReorderItemSerializer,
    RecommendationItemSerializer,
    SurplusFeedItemSerializer,
)
from .permissions import IsProducer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["category", "producer"]
    search_fields = ["name", "description"]

    def get_permissions(self):
        if self.action in ["create", "update", "destroy"]:
            return [IsProducer()]
        return []


class CategoryViewSet(viewsets.ModelViewSet):

    queryset = Category.objects.all()
    serializer_class = CategorySerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_recommendations_api(request):
    recommendations = build_customer_recommendations(request.user)
    quick_reorders = build_quick_reorder_suggestions(request.user)
    return Response(
        {
            "recommendations": RecommendationItemSerializer(recommendations, many=True).data,
            "quick_reorders": QuickReorderItemSerializer(quick_reorders, many=True).data,
            "xai_summary": "Recommendations combine your purchase history, re-order frequency, recent activity, and network-wide demand.",
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def demand_forecasts_api(request):
    if request.user.role not in {"producer", "admin"}:
        return Response(
            {"detail": "Only producers and admins can access demand forecasts."},
            status=status.HTTP_403_FORBIDDEN,
        )

    forecasts = build_demand_forecast_for_scope(request.user)
    return Response(
        {
            "scope": "producer" if request.user.role == "producer" else "network",
            "forecasts": DemandForecastItemSerializer(forecasts, many=True).data,
            "xai_summary": "Forecasts use an 8-week weighted moving average with a 20% safety buffer.",
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def food_miles_report_api(request):
    user_postcode = (request.GET.get("postcode") or request.user.postcode or "").strip()
    if not user_postcode:
        return Response(
            {"detail": "Postcode is required. Provide ?postcode=... or set your profile postcode."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    order_items = (
        OrderItem.objects.filter(order__user=request.user)
        .select_related("order", "product__producer")
        .order_by("-order__created_at")[:250]
    )

    rows = []
    total_km = 0.0
    total_miles = 0.0
    for item in order_items:
        producer_postcode = (item.product.producer.postcode or "").strip()
        if not producer_postcode:
            continue
        distance = calculate_postcode_distance(producer_postcode, user_postcode)
        total_km += distance.distance_km * item.quantity
        total_miles += distance.distance_miles * item.quantity
        rows.append(
            {
                "order_id": item.order_id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "producer": item.product.producer.username,
                "from_postcode": distance.from_postcode,
                "to_postcode": distance.to_postcode,
                "distance_km": distance.distance_km,
                "distance_miles": distance.distance_miles,
                "estimated": distance.estimated,
            }
        )

    estimated_count = sum(1 for row in rows if row["estimated"])
    return Response(
        {
            "items": FoodMilesItemSerializer(rows, many=True).data,
            "total_food_miles": round(total_miles, 2),
            "total_food_km": round(total_km, 2),
            "estimated_rows": estimated_count,
            "xai_summary": "Food miles are calculated from producer and delivery postcodes using geodesic distance (Haversine).",
        }
    )


@api_view(["GET"])
def surplus_feed_api(request):
    now = timezone.now()
    products = (
        Product.objects.filter(
            is_surplus=True,
            surplus_discount_percent__gt=0,
            surplus_expires_at__isnull=False,
            surplus_expires_at__gt=now,
            stock_quantity__gt=0,
        )
        .select_related("producer")
        .order_by("surplus_expires_at", "name")
    )

    rows = []
    for product in products:
        discount = Decimal(max(1, min(90, product.surplus_discount_percent))) / Decimal("100")
        discounted_price = (product.price * (Decimal("1") - discount)).quantize(Decimal("0.01"))
        rows.append(
            {
                "id": product.id,
                "name": product.name,
                "producer": product.producer,
                "price": product.price,
                "discounted_price": discounted_price,
                "surplus_discount_percent": product.surplus_discount_percent,
                "surplus_message": product.surplus_message,
                "surplus_expires_at": product.surplus_expires_at,
            }
        )
    return Response({"items": SurplusFeedItemSerializer(rows, many=True).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def publish_surplus_offer_api(request, product_id: int):
    if request.user.role != "producer":
        return Response({"detail": "Only producers can publish surplus offers."}, status=status.HTTP_403_FORBIDDEN)

    product = Product.objects.filter(id=product_id, producer=request.user).first()
    if not product:
        return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        discount_percent = int(request.data.get("discount_percent", 0))
    except (TypeError, ValueError):
        return Response({"detail": "discount_percent must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

    if discount_percent < 1 or discount_percent > 90:
        return Response({"detail": "discount_percent must be between 1 and 90."}, status=status.HTTP_400_BAD_REQUEST)

    expires_at_raw = request.data.get("expires_at")
    if not expires_at_raw:
        return Response({"detail": "expires_at is required (ISO datetime)."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        parsed_expires_at = timezone.datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
    except ValueError:
        return Response({"detail": "Invalid expires_at datetime format."}, status=status.HTTP_400_BAD_REQUEST)

    if timezone.is_naive(parsed_expires_at):
        parsed_expires_at = timezone.make_aware(parsed_expires_at, timezone.get_current_timezone())
    if parsed_expires_at <= timezone.now():
        return Response({"detail": "expires_at must be in the future."}, status=status.HTTP_400_BAD_REQUEST)

    message = (request.data.get("message") or "").strip()
    product.is_surplus = True
    product.surplus_discount_percent = discount_percent
    product.surplus_message = message
    product.surplus_expires_at = parsed_expires_at
    product.surplus_notified_at = timezone.now()
    product.save(
        update_fields=[
            "is_surplus",
            "surplus_discount_percent",
            "surplus_message",
            "surplus_expires_at",
            "surplus_notified_at",
        ]
    )
    return Response(
        {
            "detail": "Surplus offer published.",
            "product_id": product.id,
            "discount_percent": product.surplus_discount_percent,
            "expires_at": product.surplus_expires_at,
            "message": product.surplus_message,
        }
    )
