from django.urls import path
from .views_frontend import (
    product_list,
    product_detail,
    login_view,
    register_view,
    profile_view,
    logout_view,
    cart_view,
    checkout_view,
    add_to_cart,
    producer_add_product,
    producer_manage_products,
    producer_edit_product,
    producer_delete_product,
)

urlpatterns = [
    path("products/", product_list, name="product_list"),
    path("products/<int:pk>/", product_detail, name="product_detail"),
    path("products/<int:pk>/add/", add_to_cart, name="add_to_cart"),
    path("login/", login_view, name="login"),
    path("register/", register_view, name="register"),
    path("profile/", profile_view, name="profile"),
    path("logout/", logout_view, name="logout"),
    path("cart/", cart_view, name="cart"),
    path("checkout/", checkout_view, name="checkout"),
    path("producer/products/", producer_manage_products, name="producer_manage_products"),
    path("producer/products/add/", producer_add_product, name="producer_add_product"),
    path("producer/products/<int:pk>/edit/", producer_edit_product, name="producer_edit_product"),
    path("producer/products/<int:pk>/delete/", producer_delete_product, name="producer_delete_product"),
]
