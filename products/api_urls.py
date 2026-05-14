from rest_framework.routers import DefaultRouter
from django.urls import path

from .views import (
    CategoryViewSet,
    ProductViewSet,
    customer_recommendations_api,
    demand_forecasts_api,
    food_miles_report_api,
    publish_surplus_offer_api,
    surplus_feed_api,
)

router = DefaultRouter()

router.register("products", ProductViewSet)
router.register("categories", CategoryViewSet)

urlpatterns = router.urls + [
    path("ai/recommendations/", customer_recommendations_api, name="api_ai_recommendations"),
    path("ai/forecasts/", demand_forecasts_api, name="api_ai_forecasts"),
    path("sustainability/food-miles/", food_miles_report_api, name="api_food_miles_report"),
    path("sustainability/surplus-feed/", surplus_feed_api, name="api_surplus_feed"),
    path("sustainability/surplus/<int:product_id>/publish/", publish_surplus_offer_api, name="api_publish_surplus_offer"),
]
