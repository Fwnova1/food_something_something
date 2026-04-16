from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .forecasting import build_demand_forecast_for_scope
from .models import Category, Product
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter
from .recommendation import build_customer_recommendations, build_quick_reorder_suggestions
from .serializers import (
    CategorySerializer,
    DemandForecastItemSerializer,
    ProductSerializer,
    QuickReorderItemSerializer,
    RecommendationItemSerializer,
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
