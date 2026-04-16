from rest_framework import serializers

from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):

    class Meta:
        model = Category
        fields = '__all__'


class ProductSerializer(serializers.ModelSerializer):

    class Meta:
        model = Product
        fields = '__all__'


class RecommendationItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(source="product.id")
    product_name = serializers.CharField(source="product.name")
    producer = serializers.CharField(source="product.producer.username")
    price = serializers.DecimalField(source="product.price", max_digits=10, decimal_places=2)
    unit = serializers.CharField(source="product.unit")
    score = serializers.FloatField()
    reason = serializers.CharField()


class QuickReorderItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(source="product.id")
    product_name = serializers.CharField(source="product.name")
    producer = serializers.CharField(source="product.producer.username")
    suggested_quantity = serializers.IntegerField()
    reason = serializers.CharField()


class DemandForecastItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(source="product.id")
    product_name = serializers.CharField(source="product.name")
    producer = serializers.CharField(source="product.producer.username")
    weekly_demand = serializers.ListField(child=serializers.IntegerField())
    forecast_next_week = serializers.IntegerField()
    recommended_stock = serializers.IntegerField()
    trend = serializers.CharField()
    confidence = serializers.CharField()
    explanation = serializers.CharField()
