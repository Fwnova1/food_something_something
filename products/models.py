from django.db import models
from users.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Producer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    farm_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    postcode = models.CharField(max_length=20)

    def __str__(self):
        return self.farm_name


class Product(models.Model):
    AVAILABILITY_CHOICES = (
        ("in_season", "In Season"),
        ("year_round", "Available Year-Round"),
        ("unavailable", "Unavailable"),
    )

    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, default="item")
    availability = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES, default="year_round")
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    allergen_info = models.CharField(max_length=255, blank=True)
    harvest_date = models.DateField(null=True, blank=True)
    is_organic = models.BooleanField(default=False)
    seasonal_start = models.DateField(null=True, blank=True)
    seasonal_end = models.DateField(null=True, blank=True)

    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    producer = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE
    )

    image = models.ImageField(upload_to="products/", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def is_in_stock(self):
        return self.stock_quantity > 0


class ProductReview(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    comment = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    producer_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "user")


class ContentPost(models.Model):
    CONTENT_TYPE_CHOICES = (
        ("recipe", "Recipe"),
        ("story", "Story"),
    )
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("published", "Published"),
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, default="recipe")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()

    # Optional recipe-specific fields.
    ingredients = models.TextField(blank=True)
    steps = models.TextField(blank=True)
    prep_time_minutes = models.PositiveIntegerField(null=True, blank=True)
    cook_time_minutes = models.PositiveIntegerField(null=True, blank=True)
    servings = models.PositiveIntegerField(null=True, blank=True)

    cover_image = models.ImageField(upload_to="content/", blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    related_product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    author = models.ForeignKey("users.User", on_delete=models.CASCADE)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_content_type_display()}: {self.title}"


class QualityInspection(models.Model):
    GRADE_CHOICES = (
        ("A", "Grade A"),
        ("B", "Grade B"),
        ("C", "Grade C"),
    )

    FRESHNESS_CHOICES = (
        ("fresh", "Fresh"),
        ("rotten", "Rotten"),
        ("unknown", "Unknown"),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="quality_inspections")
    producer = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="quality_inspections")
    inspection_image = models.ImageField(upload_to="quality_inspections/", blank=True)
    produce_type = models.CharField(max_length=50, blank=True)
    freshness_label = models.CharField(max_length=20, choices=FRESHNESS_CHOICES, default="unknown")
    freshness_confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    color_score = models.PositiveSmallIntegerField()
    size_score = models.PositiveSmallIntegerField()
    ripeness_score = models.PositiveSmallIntegerField()
    overall_grade = models.CharField(max_length=1, choices=GRADE_CHOICES)
    suggested_action = models.CharField(max_length=255, blank=True)
    explanation = models.TextField(blank=True)
    assessed_by_model = models.CharField(max_length=100, default="heuristic_quality_pipeline")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - Grade {self.overall_grade} ({self.created_at:%Y-%m-%d %H:%M})"


class AIModelVersion(models.Model):
    TASK_CHOICES = (
        ("recommendation", "Recommendation"),
        ("forecasting", "Forecasting"),
        ("quality_freshness", "Quality Freshness"),
        ("quality_multi_output", "Quality Multi Output"),
    )

    task_type = models.CharField(max_length=40, choices=TASK_CHOICES)
    version_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    artifact = models.FileField(upload_to="ai_models/")
    metadata_json = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="uploaded_ai_models")
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_task_type_display()} - {self.version_name}"


class RecommendationEvent(models.Model):
    EVENT_CHOICES = (
        ("impression", "Impression"),
        ("click", "Click"),
    )

    SOURCE_CHOICES = (
        ("product_list", "Product List"),
        ("ai_insights", "AI Insights"),
        ("quick_reorder", "Quick Reorder"),
    )

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="recommendation_events")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="recommendation_events")
    producer = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="producer_recommendation_events")
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    source_page = models.CharField(max_length=30, choices=SOURCE_CHOICES)
    rank = models.PositiveIntegerField(default=1)
    score = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ForecastSnapshot(models.Model):
    viewer = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="forecast_snapshots")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="forecast_snapshots")
    producer = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="producer_forecast_snapshots")
    weekly_demand = models.CharField(max_length=255)
    forecast_next_week = models.PositiveIntegerField()
    recommended_stock = models.PositiveIntegerField()
    trend = models.CharField(max_length=20)
    confidence = models.CharField(max_length=20)
    explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class QualityInspectionOverride(models.Model):
    inspection = models.ForeignKey(QualityInspection, on_delete=models.CASCADE, related_name="overrides")
    overridden_by = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="quality_overrides")
    previous_grade = models.CharField(max_length=1)
    new_grade = models.CharField(max_length=1, choices=QualityInspection.GRADE_CHOICES)
    previous_freshness_label = models.CharField(max_length=20)
    new_freshness_label = models.CharField(max_length=20, choices=QualityInspection.FRESHNESS_CHOICES)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
