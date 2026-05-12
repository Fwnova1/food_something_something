"""Product and storefront tests (reviews, verified purchase rules)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderItem
from payments.models import Payment
from products.models import Category, Product, ProductReview
from products.views_frontend import order_has_verified_purchase

User = get_user_model()


def _session_id() -> str:
    return f"cs_test_{uuid.uuid4().hex[:24]}"


class DeliveredOrderReviewFlowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="reviewcust",
            email="reviewcust@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="reviewprod",
            email="reviewprod@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Greens")
        self.product = Product.objects.create(
            name="Kale bunch",
            description="Fresh",
            price=Decimal("3.50"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=50,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("3.50"),
            status="delivered",
            delivery_address="1 Lane",
            delivery_postcode="BS1",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal("3.50"))

    def test_order_has_verified_purchase_requires_successful_payment(self):
        self.assertFalse(order_has_verified_purchase(self.order))
        Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("3.50"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_session_id(),
            stripe_payment_intent_id="",
        )
        self.assertTrue(order_has_verified_purchase(self.order))

    def test_get_review_form_blocked_without_verified_payment(self):
        self.client.login(username="reviewcust", password="pw")
        url = reverse("submit_review", kwargs={"order_id": self.order.id, "product_id": self.product.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("order_detail", kwargs={"pk": self.order.id}))

    def test_get_review_form_allowed_when_delivered_and_paid(self):
        Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("3.50"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_session_id(),
            stripe_payment_intent_id="",
        )
        self.client.login(username="reviewcust", password="pw")
        url = reverse("submit_review", kwargs={"order_id": self.order.id, "product_id": self.product.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_post_review_creates_pending_row(self):
        Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("3.50"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_session_id(),
            stripe_payment_intent_id="",
        )
        self.client.login(username="reviewcust", password="pw")
        url = reverse("submit_review", kwargs={"order_id": self.order.id, "product_id": self.product.id})
        resp = self.client.post(
            url,
            {
                "rating": "5",
                "title": "Great greens",
                "comment": "Fresh and crisp. Would buy again.",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("order_detail", kwargs={"pk": self.order.id}))
        rev = ProductReview.objects.get(product=self.product, user=self.customer)
        self.assertEqual(rev.rating, 5)
        self.assertEqual(rev.status, "pending")

    def test_non_delivered_order_cannot_open_review_form(self):
        self.order.status = "shipped"
        self.order.save(update_fields=["status"])
        Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("3.50"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_session_id(),
            stripe_payment_intent_id="",
        )
        self.client.login(username="reviewcust", password="pw")
        url = reverse("submit_review", kwargs={"order_id": self.order.id, "product_id": self.product.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("order_detail", kwargs={"pk": self.order.id}))
