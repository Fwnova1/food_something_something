from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderItem
from products.models import Category, Product


class FinancialReportsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(username="admin1", password="pass12345", role="admin")
        self.customer = user_model.objects.create_user(username="cust1", password="pass12345", role="customer")
        self.producer_a = user_model.objects.create_user(username="producer_a", password="pass12345", role="producer")
        self.producer_b = user_model.objects.create_user(username="producer_b", password="pass12345", role="producer")

        category = Category.objects.create(name="Veg")
        self.product_a = Product.objects.create(
            name="Carrot",
            description="desc",
            price=Decimal("10.00"),
            category=category,
            producer=self.producer_a,
            stock_quantity=100,
        )
        self.product_b = Product.objects.create(
            name="Milk",
            description="desc",
            price=Decimal("10.00"),
            category=category,
            producer=self.producer_b,
            stock_quantity=100,
        )

    def test_financial_reports_requires_admin_role(self):
        self.client.login(username="cust1", password="pass12345")
        response = self.client.get(reverse("financial_reports"))
        self.assertEqual(response.status_code, 302)

    def test_financial_reports_calculates_commission_and_payout(self):
        order = Order.objects.create(user=self.customer, total=Decimal("150.00"), status="pending")
        OrderItem.objects.create(order=order, product=self.product_a, quantity=8, price=Decimal("10.00"))
        OrderItem.objects.create(order=order, product=self.product_b, quantity=7, price=Decimal("10.00"))

        self.client.login(username="admin1", password="pass12345")
        response = self.client.get(reverse("financial_reports"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GBP 7.50")
        self.assertContains(response, "GBP 76.00")
        self.assertContains(response, "GBP 66.50")

    def test_csv_export_works_for_admin(self):
        order = Order.objects.create(user=self.customer, total=Decimal("100.00"), status="pending")
        OrderItem.objects.create(order=order, product=self.product_a, quantity=10, price=Decimal("10.00"))

        self.client.login(username="admin1", password="pass12345")
        response = self.client.get(reverse("financial_reports_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("Commission (5%)", response.content.decode("utf-8"))
