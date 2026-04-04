from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django import forms
from django.contrib.auth import get_user_model
from .models import Product, Category
from orders.models import Cart, CartItem, Order, OrderItem

User = get_user_model()

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


def product_list(request):
    products = Product.objects.all()
    categories = Category.objects.all()

    category_id = request.GET.get("category")

    if category_id:
        products = products.filter(category_id=category_id)

    context = {
        "products": products,
        "categories": categories
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
        return redirect('profile')  # Or order confirmation
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
