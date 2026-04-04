from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django import forms
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import Product, Category
from orders.models import Cart, CartItem, Order, OrderItem

User = get_user_model()
TRACKING_STAGES = ["pending", "confirmed", "shipped", "delivered"]

class CustomUserCreationForm(UserCreationForm):
    ROLE_CHOICES_NO_ADMIN = (
        ('customer', 'Customer'),
        ('producer', 'Producer'),
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES_NO_ADMIN, required=True)

    class Meta:
        model = User
        fields = ("username", "email", "role")


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "description", "price", "category", "image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. Organic Tomatoes"})
        self.fields["description"].widget.attrs.update({"class": "form-control", "rows": 4, "placeholder": "Describe freshness, origin, and packaging."})
        self.fields["price"].widget.attrs.update({"class": "form-control", "placeholder": "e.g. 4.99"})
        self.fields["category"].widget.attrs.update({"class": "form-select"})
        self.fields["image"].widget.attrs.update({"class": "form-control"})


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


def product_list(request):
    products = Product.objects.all()
    categories = Category.objects.all()

    category_id = request.GET.get("category")
    search_query = (request.GET.get("q") or "").strip()

    if category_id:
        products = products.filter(category_id=category_id)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__name__icontains=search_query)
        )

    context = {
        "products": products,
        "categories": categories,
        "search_query": search_query,
    }

    return render(request, "product_list.html", context)


def product_detail(request, pk):
    product = Product.objects.get(id=pk)

    return render(
        request,
        "product_detail.html",
        {"product": product}
    )


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})


def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


@login_required
def profile_view(request):
    return render(request, 'profile.html')


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def cart_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart)
    total = sum(item.product.price * item.quantity for item in cart_items)
    return render(request, 'cart.html', {'cart_items': cart_items, 'total': total})


@login_required
def checkout_view(request):
    if request.method == 'POST':
        # Process order
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart)
        total = sum(item.product.price * item.quantity for item in cart_items)
        order = Order.objects.create(user=request.user, total=total)
        for item in cart_items:
            OrderItem.objects.create(order=order, product=item.product, quantity=item.quantity, price=item.product.price)
        cart_items.delete()  # Clear cart
        messages.success(request, "Your order has been placed successfully.")
        return redirect("order_detail", pk=order.id)
    return render(request, 'checkout.html')


@login_required
def add_to_cart(request, pk):
    product = Product.objects.get(id=pk)
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
    if not created:
        cart_item.quantity += 1
        cart_item.save()
    return redirect('cart')


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
    return render(request, "order_list.html", {"orders": orders})


@login_required
def order_detail_view(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related("orderitem_set__product__producer"),
        id=pk,
        user=request.user,
    )
    order_items = order.orderitem_set.all()
    item_rows = []
    producer_shipping_map = {}
    for item in order_items:
        item_rows.append(
            {
                "product_name": item.product.name,
                "price": item.price,
                "quantity": item.quantity,
                "subtotal": item.price * item.quantity,
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
        producer_total = sum((item.price * item.quantity for item in producer_items), 0)
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
