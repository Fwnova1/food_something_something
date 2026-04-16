from rest_framework.routers import DefaultRouter
from django.urls import path

from .views import (
    CategoryViewSet,
    ProductViewSet,
    customer_recommendations_api,
    demand_forecasts_api,
)

router = DefaultRouter()

router.register("products", ProductViewSet)
router.register("categories", CategoryViewSet)

urlpatterns = router.urls + [
    path("ai/recommendations/", customer_recommendations_api, name="api_ai_recommendations"),
    path("ai/forecasts/", demand_forecasts_api, name="api_ai_forecasts"),
]
