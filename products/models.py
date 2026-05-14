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
    is_surplus = models.BooleanField(default=False)
    surplus_discount_percent = models.PositiveSmallIntegerField(default=0)
    surplus_message = models.CharField(max_length=255, blank=True)
    surplus_expires_at = models.DateTimeField(null=True, blank=True)
    surplus_notified_at = models.DateTimeField(null=True, blank=True)

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
