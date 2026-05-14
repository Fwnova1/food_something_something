import csv
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
import json

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction
from django.db.models import Q, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils import timezone
from django.conf import settings

from orders.models import Cart, CartItem, Order, OrderItem, RecurringOrder, RecurringOrderItem
from .forecasting import build_demand_forecast_for_scope
from .models import Category, Product, ProductReview, ContentPost, QualityInspection
from .quality_inspection import inspect_product_quality
from .recommendation import build_customer_recommendations, build_quick_reorder_suggestions
from .recommendation_service import get_recommendation_service
from sustainability.services import calculate_postcode_distance

User = get_user_model()
TRACKING_STAGES = ["pending", "confirmed", "shipped", "delivered"]
COMMISSION_RATE = Decimal("0.05")
PAYOUT_RATE = Decimal("0.95")


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
    inspection_image = forms.ImageField(required=True)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["inspection_image"].widget.attrs.update({"class": "form-control"})


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

    context = {
        "products": products,
        "categories": categories,
        "search_query": search_query,
        "organic_only": organic_only,
        "recommendations": recommendations,
        "quick_reorders": quick_reorders,
    }

    return render(request, "pages/shop/product_list.html", context)


def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "producer"), id=pk)
    approved_reviews = ProductReview.objects.filter(product=product, status="approved").select_related("user").order_by("-created_at")
    review_count = approved_reviews.count()
    average_rating = None
    if review_count > 0:
        average_rating = round(sum(review.rating for review in approved_reviews) / review_count, 2)
    return render(
        request,
        "pages/shop/product_detail.html",
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
    return render(request, "pages/account/login.html", {"form": form})


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
    return render(request, "pages/account/register.html", {"form": form})


@login_required
def profile_view(request):
    context = {
        "total_orders": Order.objects.filter(user=request.user).count(),
    }
    return render(request, "pages/account/profile.html", context)


@login_required
def ai_insights_view(request):
    recommendations = []
    quick_reorders = []
    forecasts = []

    if request.user.role == "customer":
        recommendations = build_customer_recommendations(request.user, limit=6)
        quick_reorders = build_quick_reorder_suggestions(request.user, limit=4)

    if request.user.role in {"producer", "admin"}:
        forecasts = build_demand_forecast_for_scope(request.user, limit=8)

    return render(
        request,
        "pages/sustainability/ai_insights.html",
        {
            "recommendations": recommendations,
            "quick_reorders": quick_reorders,
            "forecasts": forecasts,
        },
    )


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
                                                                
    return render(request, "pages/shop/cart.html", {"cart_rows": cart_rows, "total": total})


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
        "pages/shop/checkout.html",
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
    return render(request, "pages/producer/producer_add_product.html", context)


@login_required
def producer_manage_products(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage products.")
        return redirect("profile")

    producer_products = Product.objects.filter(producer=request.user).order_by("-created_at")
    context = {
        "producer_products": producer_products,
    }
    return render(request, "pages/producer/producer_manage_products.html", context)


@login_required
def producer_quality_inspection_view(request):
    if request.user.role not in {"producer", "admin"}:
        messages.error(request, "Only producer or admin accounts can access quality inspection.")
        return redirect("profile")

    latest_result = None
    latest_gradcam_url = ""
    if request.method == "POST":
        form = QualityInspectionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            uploaded_image = form.cleaned_data.get("inspection_image")
            try:
                result = inspect_product_quality(uploaded_image, produce_hint="")
            except RuntimeError as exc:
                messages.error(request, f"Quality inspection failed: {exc}")
                return redirect("producer_quality_inspection")
            latest_result = result
            latest_gradcam_url = result.gradcam_image_url
            messages.success(request, "Quality inspection completed.")
    else:
        form = QualityInspectionForm(user=request.user)

    return render(
        request,
        "pages/producer/producer_quality_inspection.html",
        {
            "form": form,
            "latest_result": latest_result,
            "latest_gradcam_url": latest_gradcam_url,
        },
    )


@login_required
def for_you_recommendations_view(request):
    if request.user.role not in {"customer", "producer"}:
        messages.error(request, "Personalized recommendations are available for customer and producer accounts.")
        return redirect("home")

    top_n = 24
    service = get_recommendation_service()
    try:
        payload = service.recommend_for_user(request.user, top_n=top_n)
    except RuntimeError as exc:
        messages.error(request, f"Recommendations are currently unavailable: {exc}")
        return render(
            request,
            "pages/shop/for_you_recommendations.html",
            {"recommended_rows": []},
        )

    rows = payload.get("recommendations", [])
    product_ids = [row.get("product_id") for row in rows if row.get("product_id")]
    products_by_id = Product.objects.select_related("category", "producer").in_bulk(product_ids)

    recommended_rows = []
    for row in rows:
        product_id = row.get("product_id")
        product = products_by_id.get(product_id)
        if not product:
            continue
        recommended_rows.append(
            {
                "product": product,
                "probability": row.get("probability", 0.0),
                "reason": row.get("reason", "Recommended for you."),
                "explanation": row.get("explanation", ""),
                "xai_top_features": row.get("xai_top_features", []),
            }
        )

    return render(
        request,
        "pages/shop/for_you_recommendations.html",
        {"recommended_rows": recommended_rows},
    )


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

    return render(request, "pages/producer/producer_edit_product.html", {"form": form, "product": product})


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
        "pages/orders/order_list.html",
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
        "pages/orders/order_detail_tracking.html",
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

    return render(request, "pages/orders/submit_review.html", {"form": form, "product": product, "order": order})


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

    return render(request, "pages/producer/producer_order_list.html", {"order_rows": order_rows})


@login_required
def producer_review_moderation_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can moderate reviews.")
        return redirect("profile")

    reviews = ProductReview.objects.filter(product__producer=request.user).select_related("product", "user").order_by("-created_at")
    return render(request, "pages/producer/producer_review_moderation.html", {"reviews": reviews})


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
    return render(request, "pages/orders/recurring_order_list.html", {"recurring_orders": recurring_orders})


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

    return render(request, "pages/orders/recurring_order_edit.html", {"recurring": recurring, "form": form})


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


@login_required
def sustainability_report_view(request):
    user_postcode = (request.GET.get("postcode") or request.user.postcode or "").strip()
    rows = []
    total_km = Decimal("0.00")
    total_miles = Decimal("0.00")
    estimated_rows = 0

    if user_postcode:
        order_items = (
            OrderItem.objects.filter(order__user=request.user)
            .select_related("order", "product__producer")
            .order_by("-order__created_at")[:250]
        )
        for item in order_items:
            producer_postcode = (item.product.producer.postcode or "").strip()
            if not producer_postcode:
                continue
            distance = calculate_postcode_distance(producer_postcode, user_postcode)
            if distance.estimated:
                estimated_rows += 1
            line_km = Decimal(str(distance.distance_km)) * Decimal(item.quantity)
            line_miles = Decimal(str(distance.distance_miles)) * Decimal(item.quantity)
            total_km += line_km
            total_miles += line_miles
            rows.append(
                {
                    "order_id": item.order_id,
                    "product_name": item.product.name,
                    "producer_name": item.product.producer.username,
                    "quantity": item.quantity,
                    "from_postcode": distance.from_postcode,
                    "to_postcode": distance.to_postcode,
                    "distance_km": distance.distance_km,
                    "distance_miles": distance.distance_miles,
                    "line_km": round(float(line_km), 2),
                    "line_miles": round(float(line_miles), 2),
                    "estimated": distance.estimated,
                }
            )

    return render(
        request,
        "pages/sustainability/sustainability_report.html",
        {
            "rows": rows,
            "postcode": user_postcode,
            "total_km": round(float(total_km), 2),
            "total_miles": round(float(total_miles), 2),
            "estimated_rows": estimated_rows,
        },
    )


def surplus_deals_view(request):
    now = timezone.now()
    products = (
        Product.objects.filter(
            is_surplus=True,
            surplus_discount_percent__gt=0,
            surplus_expires_at__isnull=False,
            surplus_expires_at__gt=now,
            stock_quantity__gt=0,
        )
        .select_related("producer", "category")
        .order_by("surplus_expires_at", "name")
    )
    deal_rows = []
    for product in products:
        discount = Decimal(max(1, min(90, product.surplus_discount_percent))) / Decimal("100")
        discounted_price = (product.price * (Decimal("1.00") - discount)).quantize(Decimal("0.01"))
        deal_rows.append({"product": product, "discounted_price": discounted_price})
    return render(request, "pages/sustainability/surplus_deals.html", {"deal_rows": deal_rows})


@login_required
def producer_surplus_publish_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can publish surplus offers.")
        return redirect("profile")

    producer_products = Product.objects.filter(producer=request.user).select_related("category").order_by("name")
    if request.method == "POST":
        try:
            product_id = int(request.POST.get("product_id", "0"))
        except ValueError:
            messages.error(request, "Invalid product.")
            return redirect("producer_surplus_publish")

        product = Product.objects.filter(id=product_id, producer=request.user).first()
        if not product:
            messages.error(request, "Product not found.")
            return redirect("producer_surplus_publish")

        try:
            discount_percent = int(request.POST.get("discount_percent", "0"))
        except ValueError:
            messages.error(request, "Discount must be a number.")
            return redirect("producer_surplus_publish")
        if discount_percent < 1 or discount_percent > 90:
            messages.error(request, "Discount must be between 1 and 90.")
            return redirect("producer_surplus_publish")

        expires_at_value = (request.POST.get("expires_at") or "").strip()
        if not expires_at_value:
            messages.error(request, "Expiry date/time is required.")
            return redirect("producer_surplus_publish")
        try:
            parsed_expires_at = timezone.datetime.fromisoformat(expires_at_value)
        except ValueError:
            messages.error(request, "Invalid expiry date/time format.")
            return redirect("producer_surplus_publish")
        if timezone.is_naive(parsed_expires_at):
            parsed_expires_at = timezone.make_aware(parsed_expires_at, timezone.get_current_timezone())
        if parsed_expires_at <= timezone.now():
            messages.error(request, "Expiry must be in the future.")
            return redirect("producer_surplus_publish")

        product.is_surplus = True
        product.surplus_discount_percent = discount_percent
        product.surplus_expires_at = parsed_expires_at
        product.surplus_message = (request.POST.get("message") or "").strip()
        product.surplus_notified_at = timezone.now()
        product.save(
            update_fields=[
                "is_surplus",
                "surplus_discount_percent",
                "surplus_expires_at",
                "surplus_message",
                "surplus_notified_at",
            ]
        )
        messages.success(request, f"Surplus offer published for {product.name}.")
        return redirect("surplus_deals")

    return render(request, "pages/producer/producer_surplus_publish.html", {"producer_products": producer_products})


@login_required
def manager_ai_control_center_view(request):
    if request.user.role != "admin":
        messages.error(request, "Only admin accounts can access the manager control center.")
        return redirect("profile")

    upload_dir = Path(settings.BASE_DIR) / "weights" / "uploaded_recommendation_models"
    upload_dir.mkdir(parents=True, exist_ok=True)
    recommendation_config_path = upload_dir / "active_recommendation_model.json"
    quality_dir = Path(settings.BASE_DIR) / "weights" / "quality_models"
    quality_dir.mkdir(parents=True, exist_ok=True)
    quality_config_path = quality_dir / "active_quality_model.json"

    active_recommendation_model = ""
    if recommendation_config_path.exists():
        try:
            raw = json.loads(recommendation_config_path.read_text(encoding="utf-8"))
            active_recommendation_model = str(raw.get("active_model", "")).strip()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            active_recommendation_model = ""

    active_quality_model = ""
    if quality_config_path.exists():
        try:
            raw = json.loads(quality_config_path.read_text(encoding="utf-8"))
            active_quality_model = str(raw.get("active_model", "")).strip()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            active_quality_model = ""

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "upload_quality_model":
            model_file = request.FILES.get("quality_model_file")
            if not model_file:
                messages.error(request, "Please select a YOLO model file to upload.")
                return redirect("manager_ai_control_center")

            allowed_ext = {".pt", ".onnx", ".h5"}
            suffix = Path(model_file.name).suffix.lower()
            if suffix not in allowed_ext:
                messages.error(request, "Unsupported quality model format. Use .pt, .onnx, or .h5")
                return redirect("manager_ai_control_center")

            safe_name = slugify(Path(model_file.name).stem) or "quality-model"
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            target_path = quality_dir / f"{safe_name}_{timestamp}{suffix}"

            with target_path.open("wb+") as output:
                for chunk in model_file.chunks():
                    output.write(chunk)

            quality_config_path.write_text(
                json.dumps({"active_model": target_path.name, "updated_at": timezone.now().isoformat()}, indent=2),
                encoding="utf-8",
            )
            messages.success(request, f"Quality model uploaded and activated: {target_path.name}")
            return redirect("manager_ai_control_center")

        if action == "set_active_quality_model":
            selected_name = (request.POST.get("active_quality_model") or "").strip()
            selected_path = quality_dir / selected_name
            if not selected_name or not selected_path.exists() or not selected_path.is_file():
                messages.error(request, "Selected quality model does not exist.")
                return redirect("manager_ai_control_center")
            quality_config_path.write_text(
                json.dumps({"active_model": selected_name, "updated_at": timezone.now().isoformat()}, indent=2),
                encoding="utf-8",
            )
            messages.success(request, f"Active quality model set to: {selected_name}")
            return redirect("manager_ai_control_center")

        if action == "set_active_recommendation_model":
            selected_name = (request.POST.get("active_recommendation_model") or "").strip()
            selected_path = upload_dir / selected_name
            if not selected_name or not selected_path.exists() or not selected_path.is_file():
                messages.error(request, "Selected recommendation model does not exist.")
                return redirect("manager_ai_control_center")
            recommendation_config_path.write_text(
                json.dumps({"active_model": selected_name, "updated_at": timezone.now().isoformat()}, indent=2),
                encoding="utf-8",
            )
            messages.success(request, f"Active recommendation model set to: {selected_name}")
            return redirect("manager_ai_control_center")

        model_file = request.FILES.get("model_file")
        if not model_file:
            messages.error(request, "Please select a recommendation model file to upload.")
            return redirect("manager_ai_control_center")

        allowed_ext = {".pkl", ".joblib", ".pt", ".onnx", ".h5"}
        suffix = Path(model_file.name).suffix.lower()
        if suffix not in allowed_ext:
            messages.error(request, "Unsupported model format. Use .pkl, .joblib, .pt, .onnx, or .h5")
            return redirect("manager_ai_control_center")

        safe_name = slugify(Path(model_file.name).stem) or "model"
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        target_path = upload_dir / f"{safe_name}_{timestamp}{suffix}"

        with target_path.open("wb+") as output:
            for chunk in model_file.chunks():
                output.write(chunk)

        recommendation_config_path.write_text(
            json.dumps({"active_model": target_path.name, "updated_at": timezone.now().isoformat()}, indent=2),
            encoding="utf-8",
        )
        messages.success(request, f"Recommendation model uploaded and activated: {target_path.name}")
        return redirect("manager_ai_control_center")

    top_products = list(
        OrderItem.objects.values("product_id", "product__name")
        .annotate(total_qty=Count("id"))
        .order_by("-total_qty")[:8]
    )
    recent_orders = Order.objects.select_related("user").order_by("-created_at")[:10]
    recent_carts = CartItem.objects.select_related("cart__user", "product").order_by("-id")[:10]
    recent_reviews = ProductReview.objects.select_related("user", "product").order_by("-created_at")[:10]
    recent_quality_checks = QualityInspection.objects.select_related("producer", "product").order_by("-created_at")[:10]

    interaction_feed = []
    for order in recent_orders:
        interaction_feed.append(
            {
                "at": order.created_at,
                "type": "Order",
                "actor": order.user.username,
                "details": f"Order #{order.id} ({order.status}) total ${order.total}",
            }
        )
    for cart_item in recent_carts:
        interaction_feed.append(
            {
                "at": cart_item.cart.created_at,
                "type": "Cart",
                "actor": cart_item.cart.user.username,
                "details": f"Added/updated {cart_item.quantity} x {cart_item.product.name}",
            }
        )
    for review in recent_reviews:
        interaction_feed.append(
            {
                "at": review.created_at,
                "type": "Review",
                "actor": review.user.username,
                "details": f"{review.product.name} rated {review.rating}/5 ({review.status})",
            }
        )
    for inspection in recent_quality_checks:
        interaction_feed.append(
            {
                "at": inspection.created_at,
                "type": "Quality AI",
                "actor": inspection.producer.username,
                "details": f"{inspection.product.name} predicted as {inspection.freshness_label} ({inspection.freshness_confidence}%)",
            }
        )
    interaction_feed.sort(key=lambda row: row["at"], reverse=True)
    interaction_feed = interaction_feed[:30]

    now = timezone.now()
    metrics = {
        "users_total": User.objects.count(),
        "orders_24h": Order.objects.filter(created_at__gte=now - timedelta(hours=24)).count(),
        "orders_7d": Order.objects.filter(created_at__gte=now - timedelta(days=7)).count(),
        "order_items_7d": OrderItem.objects.filter(order__created_at__gte=now - timedelta(days=7)).count(),
        "reviews_7d": ProductReview.objects.filter(created_at__gte=now - timedelta(days=7)).count(),
        "quality_checks_7d": QualityInspection.objects.filter(created_at__gte=now - timedelta(days=7)).count(),
    }

    xai_preview_rows = []
    sample_user = User.objects.filter(role="customer").order_by("id").first()
    if sample_user:
        service = get_recommendation_service()
        try:
            recommendation_payload = service.recommend_for_user(sample_user, top_n=5)
            for row in recommendation_payload.get("recommendations", []):
                xai_preview_rows.append(
                    {
                        "product_name": row.get("product_name", f"Product {row.get('product_id', '')}"),
                        "probability": row.get("probability", 0.0),
                        "explanation": row.get("explanation", ""),
                        "top_features": row.get("xai_top_features", []),
                    }
                )
        except RuntimeError:
            xai_preview_rows = []

    uploaded_models = []
    for file_path in sorted(upload_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if not file_path.is_file() or file_path.name == recommendation_config_path.name:
            continue
        stat = file_path.stat()
        uploaded_models.append(
            {
                "name": file_path.name,
                "size_kb": round(stat.st_size / 1024.0, 1),
                "updated_at": timezone.datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
                "is_active": file_path.name == active_recommendation_model,
            }
        )

    quality_models = []
    for file_path in sorted(quality_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if not file_path.is_file() or file_path.name == quality_config_path.name:
            continue
        stat = file_path.stat()
        quality_models.append(
            {
                "name": file_path.name,
                "size_kb": round(stat.st_size / 1024.0, 1),
                "updated_at": timezone.datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
                "is_active": file_path.name == active_quality_model,
            }
        )

    return render(
        request,
        "pages/admin/manager_ai_control_center.html",
        {
            "metrics": metrics,
            "top_products": top_products,
            "interaction_feed": interaction_feed,
            "xai_preview_rows": xai_preview_rows,
            "uploaded_models": uploaded_models,
            "active_recommendation_model": active_recommendation_model,
            "quality_models": quality_models,
            "active_quality_model": active_quality_model,
            "sample_user": sample_user,
        },
    )


def _parse_financial_report_date(value, fallback):
    raw = (value or "").strip()
    if not raw:
        return fallback
    try:
        return timezone.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _build_financial_report_rows(start_date, end_date, status_filter="", producer_filter=None):
    quantizer = Decimal("0.01")
    orders = (
        Order.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        .select_related("user")
        .prefetch_related("orderitem_set__product__producer")
        .order_by("-created_at")
    )

    if status_filter:
        orders = orders.filter(status=status_filter)
    if producer_filter:
        orders = orders.filter(orderitem__product__producer=producer_filter).distinct()

    rows = []
    total_order_value = Decimal("0.00")
    total_commission = Decimal("0.00")
    total_payout = Decimal("0.00")

    for order in orders:
        producer_breakdown = {}
        for item in order.orderitem_set.all():
            producer = item.product.producer
            producer_key = producer.id
            line_total = (item.price * item.quantity).quantize(quantizer)
            if producer_key not in producer_breakdown:
                producer_breakdown[producer_key] = {
                    "producer_id": producer.id,
                    "producer_name": producer.business_name or producer.username,
                    "subtotal": Decimal("0.00"),
                }
            producer_breakdown[producer_key]["subtotal"] += line_total

        for entry in producer_breakdown.values():
            entry["subtotal"] = entry["subtotal"].quantize(quantizer)
            entry["commission"] = (entry["subtotal"] * COMMISSION_RATE).quantize(quantizer)
            entry["payout"] = (entry["subtotal"] * PAYOUT_RATE).quantize(quantizer)

        order_total = Decimal(order.total).quantize(quantizer)
        order_commission = (order_total * COMMISSION_RATE).quantize(quantizer)
        order_payout = (order_total * PAYOUT_RATE).quantize(quantizer)
        reconciliation_delta = (order_total - (order_commission + order_payout)).quantize(quantizer)

        rows.append(
            {
                "order": order,
                "order_total": order_total,
                "commission": order_commission,
                "payout": order_payout,
                "producer_breakdown": sorted(producer_breakdown.values(), key=lambda row: row["producer_name"].lower()),
                "reconciliation_delta": reconciliation_delta,
            }
        )
        total_order_value += order_total
        total_commission += order_commission
        total_payout += order_payout

    summary = {
        "order_count": len(rows),
        "total_order_value": total_order_value.quantize(quantizer),
        "total_commission": total_commission.quantize(quantizer),
        "total_payout": total_payout.quantize(quantizer),
    }
    return rows, summary


@login_required
def financial_reports_view(request):
    if request.user.role != "admin":
        messages.error(request, "Only admin accounts can access financial reports.")
        return redirect("profile")

    today = timezone.localdate()
    default_start = today - timedelta(days=14)

    start_date = _parse_financial_report_date(request.GET.get("start_date"), default_start)
    end_date = _parse_financial_report_date(request.GET.get("end_date"), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.GET.get("status") or "").strip()
    producer_filter_raw = (request.GET.get("producer_id") or "").strip()
    producer_filter = None
    if producer_filter_raw.isdigit():
        producer_filter = User.objects.filter(id=int(producer_filter_raw), role="producer").first()

    rows, summary = _build_financial_report_rows(start_date, end_date, status_filter=status_filter, producer_filter=producer_filter)
    producer_choices = User.objects.filter(role="producer").order_by("business_name", "username")
    status_choices = [row[0] for row in Order._meta.get_field("status").choices] if Order._meta.get_field("status").choices else []

    return render(
        request,
        "pages/admin/financial_reports.html",
        {
            "rows": rows,
            "summary": summary,
            "producer_choices": producer_choices,
            "status_choices": status_choices,
            "selected_status": status_filter,
            "selected_producer_id": producer_filter.id if producer_filter else "",
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_required
def financial_reports_export_csv_view(request):
    if request.user.role != "admin":
        return HttpResponse("Forbidden", status=403)

    today = timezone.localdate()
    start_date = _parse_financial_report_date(request.GET.get("start_date"), today - timedelta(days=14))
    end_date = _parse_financial_report_date(request.GET.get("end_date"), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.GET.get("status") or "").strip()
    producer_filter = None
    producer_filter_raw = (request.GET.get("producer_id") or "").strip()
    if producer_filter_raw.isdigit():
        producer_filter = User.objects.filter(id=int(producer_filter_raw), role="producer").first()

    rows, summary = _build_financial_report_rows(start_date, end_date, status_filter=status_filter, producer_filter=producer_filter)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="financial_report_{start_date}_{end_date}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order ID", "Created At", "Customer", "Status", "Order Total", "Commission (5%)", "Producer Payout (95%)", "Reconciliation Delta"])
    for row in rows:
        order = row["order"]
        writer.writerow(
            [
                order.id,
                timezone.localtime(order.created_at).strftime("%Y-%m-%d %H:%M"),
                order.user.username,
                order.status,
                row["order_total"],
                row["commission"],
                row["payout"],
                row["reconciliation_delta"],
            ]
        )
        for producer_row in row["producer_breakdown"]:
            writer.writerow(
                [
                    "",
                    "",
                    f"Producer: {producer_row['producer_name']}",
                    "",
                    producer_row["subtotal"],
                    producer_row["commission"],
                    producer_row["payout"],
                    "",
                ]
            )
    writer.writerow([])
    writer.writerow(["Summary"])
    writer.writerow(["Order Count", summary["order_count"]])
    writer.writerow(["Total Order Value", summary["total_order_value"]])
    writer.writerow(["Total Commission", summary["total_commission"]])
    writer.writerow(["Total Producer Payout", summary["total_payout"]])
    return response


@login_required
def financial_reports_export_pdf_view(request):
    if request.user.role != "admin":
        return HttpResponse("Forbidden", status=403)

    today = timezone.localdate()
    start_date = _parse_financial_report_date(request.GET.get("start_date"), today - timedelta(days=14))
    end_date = _parse_financial_report_date(request.GET.get("end_date"), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    status_filter = (request.GET.get("status") or "").strip()
    producer_filter = None
    producer_filter_raw = (request.GET.get("producer_id") or "").strip()
    if producer_filter_raw.isdigit():
        producer_filter = User.objects.filter(id=int(producer_filter_raw), role="producer").first()

    rows, summary = _build_financial_report_rows(start_date, end_date, status_filter=status_filter, producer_filter=producer_filter)

    # Lightweight PDF-compatible response without external dependencies.
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="financial_report_{start_date}_{end_date}.pdf"'
    lines = [
        "Financial Commission Report",
        f"Date Range: {start_date} to {end_date}",
        f"Status Filter: {status_filter or 'all'}",
        f"Producer Filter: {(producer_filter.business_name or producer_filter.username) if producer_filter else 'all'}",
        "",
        f"Order Count: {summary['order_count']}",
        f"Total Order Value: GBP {summary['total_order_value']}",
        f"Total Commission (5%): GBP {summary['total_commission']}",
        f"Total Producer Payout (95%): GBP {summary['total_payout']}",
        "",
    ]
    for row in rows:
        order = row["order"]
        lines.append(
            f"Order #{order.id} | {timezone.localtime(order.created_at).strftime('%Y-%m-%d %H:%M')} | "
            f"Status={order.status} | Total=GBP {row['order_total']} | Commission=GBP {row['commission']} | "
            f"Payout=GBP {row['payout']} | Delta=GBP {row['reconciliation_delta']}"
        )
        for producer_row in row["producer_breakdown"]:
            lines.append(
                f"  Producer {producer_row['producer_name']}: "
                f"Subtotal=GBP {producer_row['subtotal']} | "
                f"Commission=GBP {producer_row['commission']} | "
                f"Payout=GBP {producer_row['payout']}"
            )
    response.write("\n".join(lines).encode("utf-8"))
    return response


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
        "pages/content/content_list.html",
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
    return render(request, "pages/content/content_detail.html", {"post": post})


@login_required
def producer_content_list_view(request):
    if request.user.role != "producer":
        messages.error(request, "Only producer accounts can manage CMS posts.")
        return redirect("profile")

    posts = ContentPost.objects.filter(author=request.user).select_related("category", "related_product").order_by("-updated_at")
    return render(request, "pages/producer/producer_content_list.html", {"posts": posts})


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
    return render(request, "pages/producer/producer_content_form.html", {"form": form, "editing": False})


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
    return render(request, "pages/producer/producer_content_form.html", {"form": form, "editing": True, "post": post})


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

