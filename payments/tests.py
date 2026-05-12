"""Payment-focused tests (formatting, customer UI, refund admin actions)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderItem
from products.models import Category, Product

from .admin import (
    approve_refund_requests,
    process_approved_refund_requests,
    reject_refund_requests,
)
from .display import (
    build_customer_payment_history_rows,
    build_customer_payment_status_summary,
    build_payment_history_rows,
    customer_payment_status_label,
    customer_refund_request_status_label,
    format_usd,
    payment_status_label,
    quantize_money_usd,
)
from .models import Payment, PaymentEvent, RefundRequest
from .refund_service import (
    RefundProcessResult,
    _StripeRefundContext,
    _refund_prepare_committed,
)


User = get_user_model()


def _unique_session_id() -> str:
    return f"cs_test_{uuid.uuid4().hex[:24]}"


class UsdFormattingTests(TestCase):
    def test_quantize_half_up_two_decimals(self):
        self.assertEqual(quantize_money_usd(Decimal("1.005")), Decimal("1.01"))
        self.assertEqual(quantize_money_usd("10.1"), Decimal("10.10"))

    def test_format_usd_always_two_decimals_and_prefix(self):
        self.assertEqual(format_usd(Decimal("0")), "$0.00")
        self.assertEqual(format_usd(Decimal("12.3")), "$12.30")
        self.assertRegex(format_usd(Decimal("99.999")), r"^\$100\.00$")

    def test_usd_template_filter(self):
        html = Template(
            "{% load payments_tags %}{{ amount|usd }}"
        ).render(Context({"amount": Decimal("3.456")}))
        self.assertEqual(html, "$3.46")


class CustomerPaymentHistoryTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust",
            email="cust@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="prod",
            email="prod@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Vegetables")
        self.product = Product.objects.create(
            name="Kale",
            description="Green",
            price=Decimal("4.00"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=50,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("8.00"),
            status="pending",
            delivery_address="1 Main",
            delivery_postcode="12345",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price=Decimal("4.00"))
        self.payment = Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("8.00"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_unique_session_id(),
            stripe_payment_intent_id="pi_test_secret_value",
        )

    def test_customer_rows_exclude_stripe_and_use_friendly_status(self):
        rows = build_customer_payment_history_rows(self.order)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(set(row.keys()), {"status", "amount_display", "refund", "created_at", "paid_at"})
        self.assertEqual(row["status"], "Paid")
        self.assertEqual(row["amount_display"], "$8.00")
        blob = str(row).lower()
        self.assertNotIn("pi_test", blob)
        self.assertNotIn("stripe", blob)
        self.assertNotIn("session", blob)

    def test_admin_rows_include_reference_for_audit(self):
        rows = build_payment_history_rows(self.order, mask_refs=True)
        self.assertEqual(len(rows), 1)
        self.assertIn("reference", rows[0])
        self.assertIn("method", rows[0])

    def test_customer_payment_labels_never_echo_raw_database_tokens(self):
        self.assertEqual(customer_payment_status_label("not_a_real_status"), "—")
        self.assertEqual(customer_refund_request_status_label("weird_internal_slug"), "—")
        self.assertEqual(payment_status_label("unexpected_order_summary_slug"), "—")

    def test_customer_refund_failed_uses_plain_language(self):
        self.assertEqual(
            customer_refund_request_status_label(RefundRequest.Status.FAILED),
            "Couldn't complete",
        )

    def test_customer_payment_summary_refund_update_wording(self):
        RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Something went wrong",
            status=RefundRequest.Status.PENDING,
        )
        summary = build_customer_payment_status_summary(self.order)
        self.assertIn("Refund update", summary)
        self.assertNotIn("Refund:", summary)


class CustomerOrderDetailNoAuditLeakTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust2",
            email="cust2@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="prod2",
            email="prod2@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Fruit")
        self.product = Product.objects.create(
            name="Apples",
            description="Crisp",
            price=Decimal("5.00"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=10,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("5.00"),
            status="pending",
            delivery_address="2 Oak",
            delivery_postcode="99999",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal("5.00"))
        self.payment = Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("5.00"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_unique_session_id(),
            stripe_payment_intent_id="pi_super_secret",
        )
        PaymentEvent.objects.create(
            payment=self.payment,
            event_type="webhook_received",
            message="Stripe webhook received.",
            metadata={"event_type": "checkout.session.completed"},
        )
        PaymentEvent.objects.create(
            payment=self.payment,
            event_type="checkout_started",
            message="Checkout initiated.",
            metadata={},
        )

    def test_order_detail_response_excludes_internal_event_and_stripe_ids(self):
        self.client.login(username="cust2", password="pw")
        url = reverse("order_detail", kwargs={"pk": self.order.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.lower()
        self.assertNotIn(b"webhook_received", body)
        self.assertNotIn(b"checkout_started", body)
        self.assertNotIn(b"pi_super_secret", body)
        self.assertNotIn(b"evt_", body)


class CustomerRefundRequestFlowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust3",
            email="cust3@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="prod3",
            email="prod3@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Herbs")
        self.product = Product.objects.create(
            name="Basil",
            description="Fresh",
            price=Decimal("6.00"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=20,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("6.00"),
            status="pending",
            delivery_address="3 Elm",
            delivery_postcode="11111",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal("6.00"))
        self.payment = Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("6.00"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_unique_session_id(),
            stripe_payment_intent_id="pi_refund_flow",
        )

    def test_post_creates_pending_refund_and_get_shows_status(self):
        self.client.login(username="cust3", password="pw")
        url = reverse("payments:refund_request", kwargs={"order_id": self.order.pk})
        resp = self.client.post(url, {"reason": "Damaged box on arrival — please advise."})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, url)
        rr = RefundRequest.objects.get(payment=self.payment, user=self.customer)
        self.assertEqual(rr.status, RefundRequest.Status.PENDING)
        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "Under review", status_code=200)

    def test_approved_request_shows_refund_approved_for_customer(self):
        self.client.login(username="cust3", password="pw")
        url = reverse("payments:refund_request", kwargs={"order_id": self.order.pk})
        RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Please refund — item issue.",
            status=RefundRequest.Status.APPROVED,
        )
        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "Refund approved", status_code=200)

    def test_second_post_does_not_create_duplicate_when_pending(self):
        self.client.login(username="cust3", password="pw")
        url = reverse("payments:refund_request", kwargs={"order_id": self.order.pk})
        RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="first request",
            status=RefundRequest.Status.PENDING,
        )
        resp = self.client.post(url, {"reason": "Second try should not create another open request."})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RefundRequest.objects.filter(payment=self.payment, user=self.customer).count(), 1)

    def test_customer_sees_being_processed_after_prepare_committed(self):
        RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Approved — please refund.",
            status=RefundRequest.Status.APPROVED,
        )
        rr = RefundRequest.objects.get(payment=self.payment, user=self.customer)
        result = _refund_prepare_committed(rr.id)
        self.assertIsInstance(result, _StripeRefundContext)
        rr.refresh_from_db()
        self.assertEqual(rr.status, RefundRequest.Status.PROCESSING)
        self.assertIsNotNone(rr.processing_started_at)

        self.client.login(username="cust3", password="pw")
        url = reverse("payments:refund_request", kwargs={"order_id": self.order.pk})
        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "Being processed", status_code=200)


class RefundPrepareCommittedIdempotencyTests(TestCase):
    """Approved → processing is committed before the gateway call (safe resume)."""

    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust_prep",
            email="cust_prep@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="prod_prep",
            email="prod_prep@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Greens")
        self.product = Product.objects.create(
            name="Spinach",
            description="Leafy",
            price=Decimal("5.00"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=15,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("5.00"),
            status="pending",
            delivery_address="9 Oak",
            delivery_postcode="33333",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal("5.00"))
        self.payment = Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("5.00"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_unique_session_id(),
            stripe_payment_intent_id="pi_prepare_committed",
        )

    def test_second_prepare_while_processing_does_not_change_started_at(self):
        rr = RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Refund please.",
            status=RefundRequest.Status.APPROVED,
        )
        first = _refund_prepare_committed(rr.id)
        self.assertIsInstance(first, _StripeRefundContext)
        rr.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(rr.status, RefundRequest.Status.PROCESSING)
        self.assertEqual(self.payment.status, Payment.Status.REFUND_PENDING)
        started = rr.processing_started_at

        second = _refund_prepare_committed(rr.id)
        self.assertIsInstance(second, _StripeRefundContext)
        rr.refresh_from_db()
        self.assertEqual(rr.processing_started_at, started)


class RefundRequestAdminActionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staffpay",
            email="staffpay@example.com",
            password="pw",
            is_staff=True,
            role="admin",
        )
        self.customer = User.objects.create_user(
            username="cust4",
            email="cust4@example.com",
            password="pw",
            role="customer",
        )
        self.producer = User.objects.create_user(
            username="prod4",
            email="prod4@example.com",
            password="pw",
            role="producer",
        )
        self.cat = Category.objects.create(name="Roots")
        self.product = Product.objects.create(
            name="Carrots",
            description="Orange",
            price=Decimal("7.00"),
            category=self.cat,
            producer=self.producer,
            stock_quantity=30,
        )
        self.order = Order.objects.create(
            user=self.customer,
            total=Decimal("7.00"),
            status="pending",
            delivery_address="4 Pine",
            delivery_postcode="22222",
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal("7.00"))
        self.payment = Payment.objects.create(
            user=self.customer,
            order=self.order,
            amount=Decimal("7.00"),
            currency="usd",
            status=Payment.Status.SUCCEEDED,
            stripe_checkout_session_id=_unique_session_id(),
            stripe_payment_intent_id="pi_admin_actions",
        )

    def test_approve_action_updates_pending_rows(self):
        rr = RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Please refund — wrong item.",
            status=RefundRequest.Status.PENDING,
        )
        mock_admin = MagicMock()
        request = MagicMock()
        approve_refund_requests(mock_admin, request, RefundRequest.objects.filter(pk=rr.pk))
        rr.refresh_from_db()
        self.assertEqual(rr.status, RefundRequest.Status.APPROVED)
        mock_admin.message_user.assert_called_once()

    def test_reject_action_updates_pending_rows(self):
        rr = RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Please refund.",
            status=RefundRequest.Status.PENDING,
        )
        mock_admin = MagicMock()
        reject_refund_requests(mock_admin, MagicMock(), RefundRequest.objects.filter(pk=rr.pk))
        rr.refresh_from_db()
        self.assertEqual(rr.status, RefundRequest.Status.REJECTED)

    @patch("payments.admin.process_refund_request")
    def test_process_refund_action_calls_service_for_approved(self, mock_process):
        rr = RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="Approved path.",
            status=RefundRequest.Status.APPROVED,
        )
        mock_process.return_value = RefundProcessResult(refund_request=rr, outcome="processed")
        mock_admin = MagicMock()
        process_approved_refund_requests(mock_admin, MagicMock(), RefundRequest.objects.filter(pk=rr.pk))
        mock_process.assert_called_once_with(rr.id)

    @patch("payments.admin.process_refund_request")
    def test_execute_refund_admin_action_skips_processing_without_calling_service(self, mock_process):
        rr = RefundRequest.objects.create(
            payment=self.payment,
            user=self.customer,
            reason="In flight.",
            status=RefundRequest.Status.PROCESSING,
        )
        mock_admin = MagicMock()
        process_approved_refund_requests(mock_admin, MagicMock(), RefundRequest.objects.filter(pk=rr.pk))
        mock_process.assert_not_called()
