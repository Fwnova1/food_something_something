"""Orders app tests."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from orders.models import Order, OrderItem
from products.models import Category, Product

User = get_user_model()


class OrderModelSmokeTests(TestCase):
    def test_order_and_item_create(self):
        user = User.objects.create_user(username="u1", email="u1@example.com", password="pw", role="customer")
        producer = User.objects.create_user(username="p1", email="p1@example.com", password="pw", role="producer")
        cat = Category.objects.create(name="C")
        product = Product.objects.create(
            name="P",
            description="D",
            price=Decimal("1.00"),
            category=cat,
            producer=producer,
            stock_quantity=5,
        )
        order = Order.objects.create(
            user=user,
            total=Decimal("1.00"),
            status="pending",
            delivery_address="A",
            delivery_postcode="Z",
        )
        OrderItem.objects.create(order=order, product=product, quantity=1, price=Decimal("1.00"))
        self.assertEqual(order.orderitem_set.count(), 1)
