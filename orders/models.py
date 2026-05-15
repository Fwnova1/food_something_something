from django.db import models
from django.conf import settings
from products.models import Product
from decimal import Decimal, ROUND_HALF_UP

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
    # Commission fields are stored per item to support multi-producer orders.
    # We store amounts (not percentages) so reporting doesn't change if the commission rate changes later.
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    producer_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    producer_shipped = models.BooleanField(default=False)
    producer_shipped_at = models.DateTimeField(null=True, blank=True)

    COMMISSION_RATE = Decimal("0.05")

    def compute_commission_fields(self) -> None:
        """
        Compute gross/commission/producer amounts for this line item.

        This is deterministic and can be re-run safely (useful for backfills/migrations).
        """
        gross = (self.price or Decimal("0.00")) * Decimal(int(self.quantity or 0))
        commission = (gross * self.COMMISSION_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        producer = (gross - commission).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.gross_amount = gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.commission_amount = commission
        self.producer_amount = producer

    def save(self, *args, **kwargs):
        # Ensure fields stay consistent even if created outside the checkout flow.
        if (
            self.gross_amount is None
            or self.commission_amount is None
            or self.producer_amount is None
            or (self.gross_amount == Decimal("0.00") and self.quantity and self.price)
        ):
            self.compute_commission_fields()
        return super().save(*args, **kwargs)


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
