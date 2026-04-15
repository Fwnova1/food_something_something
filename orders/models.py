from django.db import models
from django.conf import settings
from products.models import Product

class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')
    delivery_address = models.CharField(max_length=255, blank=True)
    delivery_postcode = models.CharField(max_length=20, blank=True)
    customer_note = models.TextField(blank=True)

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    producer_shipped = models.BooleanField(default=False)
    producer_shipped_at = models.DateTimeField(null=True, blank=True)


class RecurringOrder(models.Model):
    FREQUENCY_CHOICES = (
        ("weekly", "Weekly"),
        ("fortnightly", "Fortnightly"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default="weekly")
    is_active = models.BooleanField(default=True)
    next_run_date = models.DateField()
    delivery_address = models.CharField(max_length=255, blank=True)
    delivery_postcode = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RecurringOrderItem(models.Model):
    recurring_order = models.ForeignKey(RecurringOrder, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
