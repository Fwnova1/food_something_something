from decimal import Decimal
from datetime import timedelta
import json

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils import timezone

from orders.models import Cart, CartItem, Order, OrderItem, RecurringOrder, RecurringOrderItem
from .forecasting import build_demand_forecast_for_scope
from .models import (
    AIModelVersion,
    Category,
    ContentPost,
    ForecastSnapshot,
    Product,
    ProductReview,
    QualityInspection,
    QualityInspectionOverride,
    RecommendationEvent,
)
from .quality_inspection import inspect_product_quality
from .recommendation import build_customer_recommendations, build_quick_reorder_suggestions

User = get_user_model()
TRACKING_STAGES = ["pending", "confirmed", "shipped", "delivered"]


class CustomUserCreationForm(UserCreationForm):
    ROLE_CHOICES_NO_ADMIN = (
        ("customer", "Customer"),
        ("producer", "Producer"),
    )

    full_name = forms.CharField(max_length=255, required=True)
    email = forms.EmailField(required=True)
    phone = forms.CharField(max_length=20, required=False)
    address = forms.CharField(max_length=255, required=False)
    postcode = forms.CharField(max_length=20, required=False)
    role = forms.ChoiceField(choices=ROLE_CHOICES_NO_ADMIN, required=True)
    business_name = forms.CharField(max_length=255, required=False)
    contact_name = forms.CharField(max_length=255, required=False)
    terms_accepted = forms.BooleanField(required=True)

    class Meta:
        model = User
        fields = (
            "full_name",
            "email",
            "phone",
            "address",
            "postcode",
            "role",
            "business_name",
            "contact_name",
            "terms_accepted",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].widget.attrs.update({"class": "form-control", "placeholder": "Your full name"})
        self.fields["email"].widget.attrs.update({"class": "form-control", "placeholder": "you@example.com"})
        self.fields["phone"].widget.attrs.update({"class": "form-control", "placeholder": "Phone number"})
        self.fields["address"].widget.attrs.update({"class": "form-control", "placeholder": "Delivery address"})
        self.fields["postcode"].widget.attrs.update({"class": "form-control", "placeholder": "Postcode"})
        self.fields["role"].widget.attrs.update({"class": "form-select"})
        self.fields["business_name"].widget.attrs.update({"class": "form-control", "placeholder": "Farm or business name"})
        self.fields["contact_name"].widget.attrs.update({"class": "form-control", "placeholder": "Main contact name"})
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})
        self.fields["terms_accepted"].widget.attrs.update({"class": "form-check-input"})

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if role == "producer" and not cleaned.get("business_name"):
            self.add_error("business_name", "Business name is required for producers.")
        if role == "producer" and not cleaned.get("contact_name"):
            self.add_error("contact_name", "Contact name is required for producers.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = self.cleaned_data.get("full_name", "").strip()
        if full_name:
            parts = full_name.split(" ", 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
            user.username = full_name.replace(" ", "").lower()

        user.email = self.cleaned_data["email"]
        user.phone = self.cleaned_data.get("phone", "")
        user.address = self.cleaned_data.get("address", "")
        user.postcode = self.cleaned_data.get("postcode", "")
        user.role = self.cleaned_data["role"]
        user.business_name = self.cleaned_data.get("business_name", "")
        user.contact_name = self.cleaned_data.get("contact_name", "")
        user.terms_accepted = self.cleaned_data.get("terms_accepted", False)

        # Ensure username uniqueness for generated usernames.
        base_username = user.username or user.email.split("@")[0]
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exclude(pk=user.pk).exists():
            suffix += 1
            username = f"{base_username}{suffix}"
        user.username = username

        if commit:
            user.save()
        return user


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "description",
            "price",
            "unit",
            "category",
            "availability",
            "stock_quantity",
            "low_stock_threshold",
            "allergen_info",
            "is_organic",
            "harvest_date",
            "seasonal_start",
            "seasonal_end",
            "image",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. Organic Tomatoes"})
        self.fields["description"].widget.attrs.update({"class": "form-control", "rows": 4, "placeholder": "Describe freshness, origin, and packaging."})
        self.fields["price"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. 4.99"})
        self.fields["unit"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. kg, dozen, litre"})
        self.fields["category"].widget.attrs.update({"class": "form-select"})
        self.fields["availability"].widget.attrs.update({"class": "form-select"})
        self.fields["stock_quantity"].widget.attrs.update({"class": "form-control", "min": 0})
        self.fields["low_stock_threshold"].widget.attrs.update({"class": "form-control", "min": 0})
        self.fields["allergen_info"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. Contains eggs, milk"})
        self.fields["is_organic"].widget.attrs.update({"class": "form-check-input"})
        self.fields["harvest_date"].widget.attrs.update({"class": "form-control", "type": "date"})
        self.fields["seasonal_start"].widget.attrs.update({"class": "form-control", "type": "date"})
        self.fields["seasonal_end"].widget.attrs.update({"class": "form-control", "type": "date"})
        self.fields["image"].widget.attrs.update({"class": "form-control"})


class ReviewForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5)
    title = forms.CharField(max_length=120)
    comment = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rating"].widget.attrs.update({"class": "form-control", "placeholder": "1 to 5"})
        self.fields["title"].widget.attrs.update({"class": "form-control", "placeholder": "Review title"})
        self.fields["comment"].widget.attrs.update({"class": "form-control", "placeholder": "Share your experience"})


class RecurringOrderForm(forms.ModelForm):
    class Meta:
        model = RecurringOrder
        fields = ("name", "frequency", "next_run_date", "delivery_address", "delivery_postcode", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update({"class": "form-control"})
        self.fields["frequency"].widget.attrs.update({"class": "form-select"})
        self.fields["next_run_date"].widget.attrs.update({"class": "form-control", "type": "date"})
        self.fields["delivery_address"].widget.attrs.update({"class": "form-control"})
        self.fields["delivery_postcode"].widget.attrs.update({"class": "form-control"})
        self.fields["is_active"].widget.attrs.update({"class": "form-check-input"})


class ContentPostForm(forms.ModelForm):
    class Meta:
        model = ContentPost
        fields = (
            "content_type",
            "title",
            "summary",
            "body",
            "ingredients",
            "steps",
            "prep_time_minutes",
            "cook_time_minutes",
            "servings",
            "cover_image",
            "category",
            "related_product",
            "status",
        )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["content_type"].widget.attrs.update({"class": "form-select"})
        self.fields["title"].widget.attrs.update({"class": "form-control", "placeholder": "Post title"})
        self.fields["summary"].widget.attrs.update({"class": "form-control", "placeholder": "Short summary for cards/listing"})
        self.fields["body"].widget.attrs.update({"class": "form-control", "rows": 8, "placeholder": "Main content"})
        self.fields["ingredients"].widget.attrs.update({"class": "form-control", "rows": 5, "placeholder": "One ingredient per line"})
        self.fields["steps"].widget.attrs.update({"class": "form-control", "rows": 6, "placeholder": "Step-by-step instructions"})
        self.fields["prep_time_minutes"].widget.attrs.update({"class": "form-control", "min": 0})
        self.fields["cook_time_minutes"].widget.attrs.update({"class": "form-control", "min": 0})
        self.fields["servings"].widget.attrs.update({"class": "form-control", "min": 1})
        self.fields["cover_image"].widget.attrs.update({"class": "form-control"})
        self.fields["category"].widget.attrs.update({"class": "form-select"})
        self.fields["related_product"].widget.attrs.update({"class": "form-select"})
        self.fields["status"].widget.attrs.update({"class": "form-select"})

        if user and user.role == "producer":
            self.fields["related_product"].queryset = Product.objects.filter(producer=user).order_by("name")


class QualityInspectionForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    inspection_image = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        queryset = Product.objects.none()
        if user:
            if user.role == "producer":
                queryset = Product.objects.filter(producer=user).order_by("name")
            elif user.role == "admin":
                queryset = Product.objects.all().order_by("name")

        self.fields["product"].queryset = queryset
        self.fields["product"].widget.attrs.update({"class": "form-select"})
        self.fields["inspection_image"].widget.attrs.update({"class": "form-control"})


class QualityOverrideForm(forms.Form):
    new_grade = forms.ChoiceField(choices=QualityInspection.GRADE_CHOICES)
    new_freshness_label = forms.ChoiceField(choices=QualityInspection.FRESHNESS_CHOICES)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_grade"].widget.attrs.update({"class": "form-select"})
        self.fields["new_freshness_label"].widget.attrs.update({"class": "form-select"})
        self.fields["note"].widget.attrs.update({"class": "form-control", "placeholder": "Why was the model corrected?"})


class AIModelUploadForm(forms.ModelForm):
    activate_immediately = forms.BooleanField(required=False, initial=True)

    class Meta:
        model = AIModelVersion
        fields = ("task_type", "version_name", "description", "artifact", "metadata_json")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_type"].widget.attrs.update({"class": "form-select"})
        self.fields["version_name"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. quality-v2"})
        self.fields["description"].widget.attrs.update({"class": "form-control", "rows": 4, "placeholder": "Training data, notes, validation summary"})
        self.fields["artifact"].widget.attrs.update({"class": "form-control"})
        self.fields["metadata_json"].widget.attrs.update({"class": "form-control", "rows": 6, "placeholder": '{"image_size": 224, "grade_labels": ["A","B","C"]}'})
        self.fields["activate_immediately"].widget.attrs.update({"class": "form-check-input"})

    def clean_metadata_json(self):
        value = (self.cleaned_data.get("metadata_json") or "").strip()
        if not value:
            return ""
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Invalid JSON metadata: {exc}")
        return value


def build_tracking_steps(status):
    if status == "cancelled":
        return [
            {"label": "Pending", "done": True},
            {"label": "Cancelled", "done": True},
        ]

    current_index = TRACKING_STAGES.index(status) if status in TRACKING_STAGES else 0
    steps = []
    for idx, label in enumerate(TRACKING_STAGES):
        steps.append(
            {
                "label": label.title(),
                "done": idx <= current_index,
                "active": idx == current_index,
            }
        )
    return steps


def _log_recommendation_impressions(user, items, source_page: str):
    if not user.is_authenticated or user.role != "customer" or not items:
        return

    RecommendationEvent.objects.bulk_create(
        [
            RecommendationEvent(
                user=user,
                product=item.product,
                producer=item.product.producer,
                event_type="impression",
                source_page=source_page,
                rank=index,
                score=getattr(item, "score", 0) or 0,
                reason=getattr(item, "reason", ""),
            )
            for index, item in enumerate(items, start=1)
        ]
    )


def _log_forecast_snapshots(user, forecasts):
    if not user.is_authenticated or user.role not in {"producer", "admin"} or not forecasts:
        return

    ForecastSnapshot.objects.bulk_create(
        [
            ForecastSnapshot(
                viewer=user,
                product=item.product,
                producer=item.product.producer,
                weekly_demand=",".join(str(value) for value in item.weekly_demand),
                forecast_next_week=item.forecast_next_week,
                recommended_stock=item.recommended_stock,
                trend=item.trend,
                confidence=item.confidence,
                explanation=item.explanation,
            )
            for item in forecasts
        ]
    )


def _available_products_queryset():
    today = timezone.localdate()
    return Product.objects.exclude(availability="unavailable").filter(stock_quantity__gt=0).filter(
        Q(availability="year_round")
        | Q(availability="in_season", seasonal_start__isnull=True, seasonal_end__isnull=True)
        | Q(availability="in_season", seasonal_start__isnull=False, seasonal_end__isnull=False, seasonal_start__lte=today, seasonal_end__gte=today)
    )


def product_list(request):
    products = _available_products_queryset().select_related("category", "producer")
    categories = Category.objects.all()
    recommendations = []
    quick_reorders = []

    category_id = request.GET.get("category")
    search_query = (request.GET.get("q") or "").strip()
    organic_only = request.GET.get("organic") == "1"

    if category_id:
        products = products.filter(category_id=category_id)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(producer__username__icontains=search_query)
            | Q(allergen_info__icontains=search_query)
        )

    if organic_only:
        products = products.filter(is_organic=True)

    if request.user.is_authenticated and request.user.role == "customer":
        recommendations = build_customer_recommendations(request.user, limit=4)
        quick_reorders = build_quick_reorder_suggestions(request.user, limit=3)
        _log_recommendation_impressions(request.user, recommendations, "product_list")

    context = {
        "products": products,
        "categories": categories,
        "search_query": search_query,
        "organic_only": organic_only,
        "recommendations": recommendations,
        "quick_reorders": quick_reorders,
    }

    return render(request, "product_list.html", context)


def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "producer"), id=pk)
    approved_reviews = ProductReview.objects.filter(product=product, status="approved").select_related("user").order_by("-created_at")
    review_count = approved_reviews.count()
    average_rating = None
    if review_count > 0:
        average_rating = round(sum(review.rating for review in approved_reviews) / review_count, 2)
    return render(
        request,
        "product_detail.html",
        {
            "product": product,
            "approved_reviews": approved_reviews,
            "review_count": review_count,
            "average_rating": average_rating,
        },
    )


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("home")
    else:
        form = AuthenticationForm()
    return render(request, "login.html", {"form": form})


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("home")
    else:
        form = CustomUserCreationForm()
    return render(request, "register.html", {"form": form})


@login_required
def profile_view(request):
    context = {
        "total_orders": Order.objects.filter(user=request.user).count(),
    }
    return render(request, "profile.html", context)


@login_required
def ai_insights_view(request):
    recommendations = []
    quick_reorders = []
    forecasts = []

    if request.user.role == "customer":
        recommendations = build_customer_recommendations(request.user, limit=6)
        quick_reorders = build_quick_reorder_suggestions(request.user, limit=4)
        _log_recommendation_impressions(request.user, recommendations, "ai_insights")

    if request.user.role in {"producer", "admin"}:
        forecasts = build_demand_forecast_for_scope(request.user, limit=8)
        _log_forecast_snapshots(request.user, forecasts)

    return render(
        request,
        "ai_insights.html",
        {
            "recommendations": recommendations,
            "quick_reorders": quick_reorders,
            "forecasts": forecasts,
        },
    )


@login_required
def open_recommended_product(request, pk):
    source = request.GET.get("source") or "ai_insights"
    valid_sources = {"product_list", "ai_insights", "quick_reorder"}
    if source not in valid_sources:
        source = "ai_insights"

    product = get_object_or_404(Product.objects.select_related("producer"), id=pk)
    if request.user.role == "customer":
        try:
            rank = max(1, int(request.GET.get("rank", "1") or 1))
        except (TypeError, ValueError):
            rank = 1
        try:
            score = Decimal(str(request.GET.get("score", "0") or "0"))
        except Exception:
            score = Decimal("0")

        RecommendationEvent.objects.create(
            user=request.user,
            product=product,
            producer=product.producer,
            event_type="click",
            source_page=source,
            rank=rank,
            score=score,
            reason=(request.GET.get("reason") or "")[:255],
        )

    return redirect("product_detail", pk=product.id)


@login_required
def admin_ai_dashboard_view(request):
    if request.user.role != "admin":
        messages.error(request, "Only admin accounts can access the AI dashboard.")
        return redirect("profile")

    model_versions = AIModelVersion.objects.select_related("uploaded_by").order_by("-created_at")
    active_models = model_versions.filter(is_active=True)
    recommendation_event_count = RecommendationEvent.objects.filter(event_type="impression").count()
    recommendation_click_count = RecommendationEvent.objects.filter(event_type="click").count()
    quality_override_count = QualityInspectionOverride.objects.count()
    inspection_count = QualityInspection.objects.count()
    forecast_snapshot_count = ForecastSnapshot.objects.count()

    click_through_rate = 0.0
    if recommendation_event_count:
        click_through_rate = round((recommendation_click_count / recommendation_event_count) * 100.0, 2)

    override_rate = 0.0
    if inspection_count:
        override_rate = round((quality_override_count / inspection_count) * 100.0, 2)

    producer_exposure = (
        RecommendationEvent.objects.filter(event_type="impression")
        .values("producer__username")
        .annotate(impressions=Count("id"))
        .order_by("-impressions")[:10]
    )

    recent_overrides = QualityInspectionOverride.objects.select_related("inspection__product", "overridden_by")[:10]
    recent_forecasts = ForecastSnapshot.objects.select_related("product", "producer")[:10]

    return render(
        request,
        "admin_ai_dashboard.html",
        {
            "model_versions": model_versions[:15],
            "active_models": active_models,
            "recommendation_event_count": recommendation_event_count,
            "recommendation_click_count": recommendation_click_count,
            "forecast_snapshot_count": forecast_snapshot_count,
            "inspection_count": inspection_count,
            "quality_override_count": quality_override_count,
            "click_through_rate": click_through_rate,
            "override_rate": override_rate,
            "producer_exposure": producer_exposure,
            "recent_overrides": recent_overrides,
            "recent_forecasts": recent_forecasts,
        },
    )


@login_required
def admin_ai_model_upload_view(request):
    if request.user.role != "admin":
        messages.error(request, "Only admin accounts can upload AI models.")
        return redirect("profile")

    if request.method == "POST":
        form = AIModelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            model_version = form.save(commit=False)
            model_version.uploaded_by = request.user
            activate_immediately = form.cleaned_data.get("activate_immediately")
            if activate_immediately:
                AIModelVersion.objects.filter(task_type=model_version.task_type, is_active=True).update(is_active=False)
                model_version.is_active = True
                model_version.activated_at = timezone.now()
            model_version.save()
            messages.success(request, f"Model '{model_version.version_name}' uploaded successfully.")
            return redirect("admin_ai_dashboard")
    else:
        form = AIModelUploadForm()

    model_versions = AIModelVersion.objects.select_related("uploaded_by").order_by("-created_at")[:15]
    return render(request, "admin_ai_model_upload.html", {"form": form, "model_versions": model_versions})


def logout_view(request):
    logout(request)
    return redirect("home")


@login_required
def cart_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related("product__category", "product__producer")

    cart_rows = []
    total = Decimal("0.00")
    for item in cart_items:
        line_total = item.product.price * item.quantity
        total += line_total
        cart_rows.append(
            {
                "id": item.id,
                "product": item.product,
                "quantity": item.quantity,
                "line_total": line_total,
            }
        )

    return render(request, "cart.html", {"cart_rows": cart_rows, "total": total})


@login_required
def update_cart_item(request, item_id):
    if request.method != "POST":
        return redirect("cart")

    cart = get_object_or_404(Cart, user=request.user)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)

    try:
        quantity = int(request.POST.get("quantity", item.quantity))
    except ValueError:
        messages.error(request, "Invalid quantity value.")
        return redirect("cart")

    if quantity <= 0:
        item.delete()
        messages.success(request, "Item removed from cart.")
        return redirect("cart")

    if quantity > item.product.stock_quantity:
        messages.error(request, f"Only {item.product.stock_quantity} in stock for {item.product.name}.")
        return redirect("cart")

    item.quantity = quantity
    item.save(update_fields=["quantity"])
    messages.success(request, "Cart updated.")
    return redirect("cart")


@login_required
def remove_cart_item(request, item_id):
    if request.method != "POST":
        return redirect("cart")

    cart = get_object_or_404(Cart, user=request.user)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)
    item.delete()
    messages.success(request, "Item removed from cart.")
    return redirect("cart")


@login_required
def checkout_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related("product")

    if request.method == "POST":
        delivery_address = (request.POST.get("address") or request.user.address or "").strip()
        delivery_postcode = (request.POST.get("postcode") or request.user.postcode or "").strip()
        customer_note = (request.POST.get("customer_note") or "").strip()

        if not delivery_address or not delivery_postcode:
            messages.error(request, "Delivery address and postcode are required.")
            return redirect("checkout")

        with transaction.atomic():
            refreshed_items = list(CartItem.objects.select_related("product").filter(cart=cart).select_for_update())
            if not refreshed_items:
                messages.error(request, "Your cart is empty.")
                return redirect("cart")

            total = Decimal("0.00")
            for item in refreshed_items:
                if item.quantity > item.product.stock_quantity:
                    messages.error(request, f"Insufficient stock for {item.product.name}.")
                    return redirect("cart")
                total += item.product.price * item.quantity

            order = Order.objects.create(
                user=request.user,
                total=total,
                delivery_address=delivery_address,
                delivery_postcode=delivery_postcode,
                customer_note=customer_note,
            )

            for item in refreshed_items:
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    price=item.product.price,
                )
                item.product.stock_quantity -= item.quantity
                item.product.save(update_fields=["stock_quantity"])

            CartItem.objects.filter(cart=cart).delete()

        messages.success(request, "Your order has been placed successfully.")
        return redirect("order_detail", pk=order.id)

    return render(
        request,
        "checkout.html",
        {
            "default_address": request.user.address,
            "default_postcode": request.user.postcode,
        },
    )


@login_required
def add_to_cart(request, pk):
    product = get_object_or_404(Product, id=pk)

    if product.availability == "unavailable" or product.stock_quantity <= 0:
        messages.error(request, "This product is currently unavailable.")
        return redirect("product_detail", pk=pk)

    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
    if not created:
        if cart_item.quantity + 1 > product.stock_quantity:
            messages.error(request, f"Only {product.stock_quantity} in stock for {product.name}.")
            return redirect("cart")
        cart_item.quantity += 1
        cart_item.save(update_fields=["quantity"])

    messages.success(request, f"{product.name} added to cart.")
    return redirect("cart")


@login_required
def producer_add_product(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can add products.")
        return redirect("profile")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.producer = request.user
            product.save()
            messages.success(request, f"Product '{product.name}' created successfully.")
            return redirect("product_detail", pk=product.id)
    else:
        form = ProductForm()

    producer_products = Product.objects.filter(producer=request.user).order_by("-created_at")
    context = {
        "form": form,
        "producer_products": producer_products,
    }
    return render(request, "producer_add_product.html", context)


@login_required
def producer_manage_products(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage products.")
        return redirect("profile")

    producer_products = Product.objects.filter(producer=request.user).order_by("-created_at")
    context = {
        "producer_products": producer_products,
    }
    return render(request, "producer_manage_products.html", context)


@login_required
def producer_quality_inspection_view(request):
    if request.user.role not in {"producer", "admin"}:
        messages.error(request, "Only producer or admin accounts can access quality inspection.")
        return redirect("profile")

    latest_result = None
    if request.method == "POST":
        form = QualityInspectionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            product = form.cleaned_data["product"]
            uploaded_image = form.cleaned_data.get("inspection_image")

            if not uploaded_image and not product.image:
                messages.error(request, "Upload an inspection image or add an image to the selected product first.")
                return redirect("producer_quality_inspection")

            image_source = uploaded_image or product.image
            result = inspect_product_quality(product, image_source)
            inspection = QualityInspection.objects.create(
                product=product,
                producer=product.producer,
                inspection_image=uploaded_image if uploaded_image else None,
                produce_type=result.produce_type,
                freshness_label=result.freshness_label,
                freshness_confidence=result.freshness_confidence,
                color_score=result.color_score,
                size_score=result.size_score,
                ripeness_score=result.ripeness_score,
                overall_grade=result.overall_grade,
                suggested_action=result.suggested_action,
                explanation=result.explanation,
                assessed_by_model=result.assessed_by_model,
            )
            latest_result = inspection
            messages.success(request, f"Quality inspection completed for {product.name}.")
    else:
        form = QualityInspectionForm(user=request.user)

    inspections = QualityInspection.objects.select_related("product", "producer").prefetch_related("overrides__overridden_by")
    if request.user.role == "producer":
        inspections = inspections.filter(producer=request.user)
    inspections = inspections.order_by("-created_at")[:12]

    return render(
        request,
        "producer_quality_inspection.html",
        {
            "form": form,
            "override_form": QualityOverrideForm(),
            "latest_result": latest_result,
            "inspections": inspections,
        },
    )


@login_required
def quality_inspection_override_view(request, inspection_id):
    inspection = get_object_or_404(QualityInspection.objects.select_related("product", "producer"), id=inspection_id)
    if request.user.role not in {"producer", "admin"}:
        messages.error(request, "Only producer or admin accounts can override AI quality results.")
        return redirect("profile")
    if request.user.role == "producer" and inspection.producer_id != request.user.id:
        messages.error(request, "You can only override inspections for your own products.")
        return redirect("producer_quality_inspection")
    if request.method != "POST":
        return redirect("producer_quality_inspection")

    form = QualityOverrideForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid override submission.")
        return redirect("producer_quality_inspection")

    QualityInspectionOverride.objects.create(
        inspection=inspection,
        overridden_by=request.user,
        previous_grade=inspection.overall_grade,
        new_grade=form.cleaned_data["new_grade"],
        previous_freshness_label=inspection.freshness_label,
        new_freshness_label=form.cleaned_data["new_freshness_label"],
        note=form.cleaned_data.get("note", ""),
    )
    inspection.overall_grade = form.cleaned_data["new_grade"]
    inspection.freshness_label = form.cleaned_data["new_freshness_label"]
    inspection.explanation = (
        f"{inspection.explanation} Override applied by {request.user.username}: "
        f"grade {form.cleaned_data['new_grade']}, freshness {form.cleaned_data['new_freshness_label']}."
    ).strip()
    inspection.save(update_fields=["overall_grade", "freshness_label", "explanation"])
    messages.success(request, "Quality inspection override saved.")
    return redirect("producer_quality_inspection")


@login_required
def producer_edit_product(request, pk):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can edit products.")
        return redirect("profile")

    product = get_object_or_404(Product, id=pk, producer=request.user)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Product '{product.name}' updated successfully.")
            return redirect("producer_manage_products")
    else:
        form = ProductForm(instance=product)

    return render(request, "producer_edit_product.html", {"form": form, "product": product})


@login_required
def producer_delete_product(request, pk):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can delete products.")
        return redirect("profile")

    product = get_object_or_404(Product, id=pk, producer=request.user)

    if request.method == "POST":
        deleted_name = product.name
        product.delete()
        messages.success(request, f"Product '{deleted_name}' was deleted.")
        return redirect("producer_manage_products")

    messages.error(request, "Invalid request for deleting a product.")
    return redirect("producer_manage_products")


@login_required
def order_list_view(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at")

    producer_filter = (request.GET.get("producer") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    if producer_filter:
        orders = orders.filter(orderitem__product__producer__username__icontains=producer_filter).distinct()
    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)
    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)

    return render(
        request,
        "order_list.html",
        {
            "orders": orders,
            "producer_filter": producer_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@login_required
def reorder_order(request, pk):
    if request.method != "POST":
        return redirect("order_list")

    order = get_object_or_404(Order.objects.prefetch_related("orderitem_set__product"), id=pk, user=request.user)
    cart, _ = Cart.objects.get_or_create(user=request.user)

    unavailable = []
    for item in order.orderitem_set.all():
        product = item.product
        if product.availability == "unavailable" or product.stock_quantity <= 0:
            unavailable.append(product.name)
            continue

        target_qty = min(item.quantity, product.stock_quantity)
        cart_item, _ = CartItem.objects.get_or_create(cart=cart, product=product)
        cart_item.quantity = min(cart_item.quantity + target_qty, product.stock_quantity)
        cart_item.save(update_fields=["quantity"])

    if unavailable:
        messages.warning(request, "Some items were unavailable: " + ", ".join(unavailable))
    else:
        messages.success(request, "Items added to cart from previous order.")

    return redirect("cart")


@login_required
def order_detail_view(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related("orderitem_set__product__producer"),
        id=pk,
        user=request.user,
    )
    order_items = order.orderitem_set.all()
    reviewed_product_ids = set(
        ProductReview.objects.filter(user=request.user, product__in=[oi.product for oi in order_items]).values_list("product_id", flat=True)
    )
    item_rows = []
    producer_shipping_map = {}
    for item in order_items:
        item_rows.append(
            {
                "product_id": item.product.id,
                "product_name": item.product.name,
                "price": item.price,
                "quantity": item.quantity,
                "subtotal": item.price * item.quantity,
                "producer_name": item.product.producer.username,
                "can_review": order.status == "delivered" and item.product_id not in reviewed_product_ids,
            }
        )
        producer_entry = producer_shipping_map.setdefault(
            item.product.producer_id,
            {
                "producer_name": item.product.producer.username,
                "shipped": True,
            },
        )
        producer_entry["shipped"] = producer_entry["shipped"] and item.producer_shipped

    shipping_summary = list(producer_shipping_map.values())
    tracking_steps = build_tracking_steps(order.status)
    return render(
        request,
        "order_detail_tracking.html",
        {
            "order": order,
            "item_rows": item_rows,
            "shipping_summary": shipping_summary,
            "tracking_steps": tracking_steps,
        },
    )


@login_required
def submit_review_view(request, order_id, product_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status != "delivered":
        messages.error(request, "You can review only delivered orders.")
        return redirect("order_detail", pk=order.id)

    order_item_exists = OrderItem.objects.filter(order=order, product_id=product_id).exists()
    if not order_item_exists:
        messages.error(request, "Product not found in this order.")
        return redirect("order_detail", pk=order.id)

    product = get_object_or_404(Product, id=product_id)
    existing = ProductReview.objects.filter(product=product, user=request.user).first()
    if existing:
        messages.info(request, "You already reviewed this product.")
        return redirect("product_detail", pk=product.id)

    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            ProductReview.objects.create(
                product=product,
                user=request.user,
                rating=form.cleaned_data["rating"],
                title=form.cleaned_data["title"],
                comment=form.cleaned_data["comment"],
                status="pending",
            )
            messages.success(request, "Review submitted and pending moderation.")
            return redirect("product_detail", pk=product.id)
    else:
        form = ReviewForm()

    return render(request, "submit_review.html", {"form": form, "product": product, "order": order})


@login_required
def producer_order_list_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage order confirmations.")
        return redirect("profile")

    orders = (
        Order.objects.filter(orderitem__product__producer=request.user)
        .select_related("user")
        .prefetch_related("orderitem_set__product")
        .distinct()
        .order_by("-created_at")
    )

    order_rows = []
    for order in orders:
        producer_items = [item for item in order.orderitem_set.all() if item.product.producer_id == request.user.id]
        producer_total = sum((item.price * item.quantity for item in producer_items), Decimal("0.00"))
        producer_quantity = sum((item.quantity for item in producer_items), 0)
        producer_shipped = bool(producer_items) and all(item.producer_shipped for item in producer_items)
        all_items = list(order.orderitem_set.all())
        total_producers = len({item.product.producer_id for item in all_items})
        shipped_producers = len({item.product.producer_id for item in all_items if item.producer_shipped})
        order_rows.append(
            {
                "order": order,
                "producer_items": producer_items,
                "producer_total": producer_total,
                "producer_quantity": producer_quantity,
                "producer_shipped": producer_shipped,
                "total_producers": total_producers,
                "shipped_producers": shipped_producers,
            }
        )

    return render(request, "producer_order_list.html", {"order_rows": order_rows})


@login_required
def producer_review_moderation_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can moderate reviews.")
        return redirect("profile")

    reviews = ProductReview.objects.filter(product__producer=request.user).select_related("product", "user").order_by("-created_at")
    return render(request, "producer_review_moderation.html", {"reviews": reviews})


@login_required
def producer_review_action_view(request, review_id):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can moderate reviews.")
        return redirect("profile")

    review = get_object_or_404(ProductReview, id=review_id, product__producer=request.user)
    if request.method != "POST":
        return redirect("producer_review_moderation")

    action = request.POST.get("action")
    response = (request.POST.get("producer_response") or "").strip()
    if action == "approve":
        review.status = "approved"
    elif action == "reject":
        review.status = "rejected"

    if response:
        review.producer_response = response
    review.save()
    messages.success(request, "Review moderation updated.")
    return redirect("producer_review_moderation")


@login_required
def producer_confirm_order_view(request, pk):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can confirm orders.")
        return redirect("profile")

    order = get_object_or_404(Order, id=pk, orderitem__product__producer=request.user)

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("producer_order_list")

    if order.status == "pending":
        order.status = "confirmed"
        order.save(update_fields=["status"])
        messages.success(request, f"Order #{order.id} has been confirmed.")
    else:
        messages.info(request, f"Order #{order.id} is already '{order.status}'.")

    return redirect("producer_order_list")


@login_required
def producer_ship_order_view(request, pk):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can mark orders as shipped.")
        return redirect("profile")

    order = get_object_or_404(Order, id=pk, orderitem__product__producer=request.user)

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("producer_order_list")

    if order.status == "confirmed":
        producer_items_qs = OrderItem.objects.filter(order=order, product__producer=request.user)
        updated_count = producer_items_qs.filter(producer_shipped=False).update(
            producer_shipped=True,
            producer_shipped_at=timezone.now(),
        )

        if updated_count == 0:
            messages.info(request, f"You already marked your items as shipped for order #{order.id}.")
            return redirect("producer_order_list")

        all_shipped = not OrderItem.objects.filter(order=order, producer_shipped=False).exists()
        if all_shipped:
            order.status = "shipped"
            order.save(update_fields=["status"])
            messages.success(request, f"All vendors shipped order #{order.id}. Order is now marked shipped.")
        else:
            messages.success(
                request,
                f"Your items for order #{order.id} are marked shipped. Waiting for other vendors.",
            )
    elif order.status == "pending":
        messages.info(request, f"Order #{order.id} must be confirmed before shipping.")
    else:
        messages.info(request, f"Order #{order.id} is already '{order.status}'.")

    return redirect("producer_order_list")


@login_required
def customer_confirm_delivery_view(request, pk):
    order = get_object_or_404(Order, id=pk, user=request.user)

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("order_detail", pk=order.id)

    if order.status == "shipped":
        order.status = "delivered"
        order.save(update_fields=["status"])
        messages.success(request, f"Order #{order.id} has been marked as delivered.")
    elif order.status == "delivered":
        messages.info(request, f"Order #{order.id} is already delivered.")
    else:
        messages.info(request, f"Order #{order.id} cannot be marked delivered from '{order.status}'.")

    return redirect("order_detail", pk=order.id)


@login_required
def recurring_order_list_view(request):
    recurring_orders = (
        RecurringOrder.objects.filter(user=request.user)
        .prefetch_related("recurringorderitem_set__product")
        .order_by("-created_at")
    )
    return render(request, "recurring_order_list.html", {"recurring_orders": recurring_orders})


@login_required
def create_recurring_from_order_view(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("orderitem_set__product"), id=order_id, user=request.user)
    if request.method != "POST":
        return redirect("order_detail", pk=order.id)

    next_run_date = timezone.localdate() + timedelta(days=7)
    recurring = RecurringOrder.objects.create(
        user=request.user,
        name=f"Recurring from Order #{order.id}",
        frequency="weekly",
        next_run_date=next_run_date,
        delivery_address=order.delivery_address or request.user.address,
        delivery_postcode=order.delivery_postcode or request.user.postcode,
        is_active=True,
    )

    for item in order.orderitem_set.all():
        RecurringOrderItem.objects.create(recurring_order=recurring, product=item.product, quantity=item.quantity)

    messages.success(request, "Recurring order template created.")
    return redirect("recurring_order_list")


@login_required
def recurring_order_edit_view(request, recurring_id):
    recurring = get_object_or_404(
        RecurringOrder.objects.prefetch_related("recurringorderitem_set__product"),
        id=recurring_id,
        user=request.user,
    )

    if request.method == "POST":
        form = RecurringOrderForm(request.POST, instance=recurring)
        if form.is_valid():
            form.save()
            for item in recurring.recurringorderitem_set.all():
                key = f"qty_{item.id}"
                if key in request.POST:
                    try:
                        qty = int(request.POST.get(key))
                    except (TypeError, ValueError):
                        qty = item.quantity
                    item.quantity = max(1, qty)
                    item.save(update_fields=["quantity"])
            messages.success(request, "Recurring order updated.")
            return redirect("recurring_order_list")
    else:
        form = RecurringOrderForm(instance=recurring)

    return render(request, "recurring_order_edit.html", {"recurring": recurring, "form": form})


@login_required
def recurring_order_generate_now_view(request, recurring_id):
    recurring = get_object_or_404(
        RecurringOrder.objects.prefetch_related("recurringorderitem_set__product"),
        id=recurring_id,
        user=request.user,
    )
    if request.method != "POST":
        return redirect("recurring_order_list")

    if not recurring.is_active:
        messages.error(request, "Recurring order is paused.")
        return redirect("recurring_order_list")

    recurring_items = recurring.recurringorderitem_set.all()
    if not recurring_items:
        messages.error(request, "Recurring order has no items.")
        return redirect("recurring_order_list")

    unavailable = []
    total = Decimal("0.00")
    with transaction.atomic():
        lock_items = list(recurring.recurringorderitem_set.select_related("product").select_for_update())
        for recurring_item in lock_items:
            product = recurring_item.product
            if product.availability == "unavailable" or product.stock_quantity < recurring_item.quantity:
                unavailable.append(product.name)

        if unavailable:
            messages.error(request, "Cannot generate order. Unavailable items: " + ", ".join(unavailable))
            return redirect("recurring_order_list")

        order = Order.objects.create(
            user=request.user,
            total=Decimal("0.00"),
            status="pending",
            delivery_address=recurring.delivery_address or request.user.address,
            delivery_postcode=recurring.delivery_postcode or request.user.postcode,
            customer_note=f"Auto-generated from recurring order '{recurring.name}'",
        )

        for recurring_item in lock_items:
            product = recurring_item.product
            qty = recurring_item.quantity
            OrderItem.objects.create(order=order, product=product, quantity=qty, price=product.price)
            product.stock_quantity -= qty
            product.save(update_fields=["stock_quantity"])
            total += product.price * qty

        order.total = total.quantize(Decimal("0.01"))
        order.save(update_fields=["total"])

    if recurring.frequency == "weekly":
        recurring.next_run_date = recurring.next_run_date + timedelta(days=7)
    else:
        recurring.next_run_date = recurring.next_run_date + timedelta(days=14)
    recurring.save(update_fields=["next_run_date"])

    messages.success(request, f"New order #{order.id} generated from recurring template.")
    return redirect("order_detail", pk=order.id)


@login_required
def recurring_order_delete_view(request, recurring_id):
    recurring = get_object_or_404(RecurringOrder, id=recurring_id, user=request.user)
    if request.method == "POST":
        recurring.delete()
        messages.success(request, "Recurring order deleted.")
    return redirect("recurring_order_list")


def _unique_content_slug(title, current_post=None):
    base = slugify(title)[:180] or "post"
    slug = base
    counter = 2
    while ContentPost.objects.filter(slug=slug).exclude(pk=getattr(current_post, "pk", None)).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def content_list_view(request):
    content_type = (request.GET.get("type") or "").strip()
    query = (request.GET.get("q") or "").strip()

    posts = ContentPost.objects.filter(status="published").select_related("author", "category", "related_product").order_by("-published_at", "-created_at")
    if content_type in {"recipe", "story"}:
        posts = posts.filter(content_type=content_type)
    if query:
        posts = posts.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(body__icontains=query))

    return render(
        request,
        "content_list.html",
        {
            "posts": posts,
            "content_type": content_type,
            "search_query": query,
        },
    )


def content_detail_view(request, slug):
    post = get_object_or_404(ContentPost.objects.select_related("author", "category", "related_product"), slug=slug)
    can_view_unpublished = request.user.is_authenticated and (
        request.user.role == "admin" or (request.user.role == "producer" and post.author_id == request.user.id)
    )
    if post.status != "published" and not can_view_unpublished:
        messages.error(request, "This post is not available.")
        return redirect("content_list")
    return render(request, "content_detail.html", {"post": post})


@login_required
def producer_content_list_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage CMS posts.")
        return redirect("profile")

    posts = ContentPost.objects.filter(author=request.user).select_related("category", "related_product").order_by("-updated_at")
    return render(request, "producer_content_list.html", {"posts": posts})


@login_required
def producer_content_create_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage CMS posts.")
        return redirect("profile")

    if request.method == "POST":
        form = ContentPostForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.slug = _unique_content_slug(post.title)
            if post.status == "published":
                post.published_at = timezone.now()
            post.save()
            messages.success(request, "Post created successfully.")
            return redirect("producer_content_list")
    else:
        form = ContentPostForm(user=request.user)
    return render(request, "producer_content_form.html", {"form": form, "editing": False})


@login_required
def producer_content_edit_view(request, post_id):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage CMS posts.")
        return redirect("profile")

    post = get_object_or_404(ContentPost, id=post_id, author=request.user)
    if request.method == "POST":
        old_title = post.title
        old_status = post.status
        form = ContentPostForm(request.POST, request.FILES, instance=post, user=request.user)
        if form.is_valid():
            edited_post = form.save(commit=False)
            if old_title != edited_post.title:
                edited_post.slug = _unique_content_slug(edited_post.title, current_post=edited_post)
            if old_status != "published" and edited_post.status == "published":
                edited_post.published_at = timezone.now()
            edited_post.save()
            messages.success(request, "Post updated successfully.")
            return redirect("producer_content_list")
    else:
        form = ContentPostForm(instance=post, user=request.user)
    return render(request, "producer_content_form.html", {"form": form, "editing": True, "post": post})


@login_required
def producer_content_delete_view(request, post_id):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage CMS posts.")
        return redirect("profile")

    post = get_object_or_404(ContentPost, id=post_id, author=request.user)
    if request.method == "POST":
        post.delete()
        messages.success(request, "Post deleted.")
    return redirect("producer_content_list")
