from django.urls import path
from .views_frontend import product_list, product_detail, login_view, register_view, profile_view, logout_view, cart_view, checkout_view, add_to_cart

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
]