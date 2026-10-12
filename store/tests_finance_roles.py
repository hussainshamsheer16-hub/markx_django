from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, Expense, Order, OrderAuditLog, OrderItem, Product


class FinanceReportTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser("owner", "owner@example.com", "test-password")
        category, _ = Category.objects.get_or_create(name="Shirts")
        product = Product.objects.create(name="Finance test shirt", slug="finance-test-shirt", category=category, price=1000, cost_price=Decimal("400"), image="products/test.png")
        delivered = Order.objects.create(full_name="A", phone="03001234567", address="A", city="A", payment_method="cod", status="delivered", subtotal=2000, discount=100, delivery=0, total=1900, shipping_cost=Decimal("50"))
        pending = Order.objects.create(full_name="B", phone="03001234567", address="B", city="B", status="pending", subtotal=800, total=800)
        cancelled = Order.objects.create(full_name="C", phone="03001234567", address="C", city="C", status="cancelled", subtotal=500, total=500)
        OrderItem.objects.create(order=delivered, product=product, name=product.name, size="M", color="Black", price=1000, cost_price=Decimal("400"), qty=2)
        OrderItem.objects.create(order=pending, product=product, name=product.name, size="M", color="Black", price=800, cost_price=Decimal("300"), qty=1)
        OrderItem.objects.create(order=cancelled, product=product, name=product.name, size="M", color="Black", price=500, cost_price=Decimal("100"), qty=1)
        Expense.objects.create(date=timezone.localdate(), category="Packaging", title="Boxes", amount=Decimal("200"), created_by=self.owner)

    def test_finance_report_totals_respect_cost_expense_and_cancelled_order(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("store:finance_dashboard"), {"range": "30d"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["revenue"], 2700)
        self.assertEqual(response.context["cogs"], Decimal("1100"))
        self.assertEqual(response.context["gross_profit"], Decimal("1550"))
        self.assertEqual(response.context["expense_total"], Decimal("200"))
        self.assertEqual(response.context["net_profit"], Decimal("1350"))
        self.assertEqual(response.context["margin"], 57.4)
        self.assertEqual(response.context["orders_count"], 2)
        self.assertEqual(response.context["aov"], 1350)
        self.assertEqual(sum(row["profit"] for row in response.context["product_rows"]), response.context["gross_profit"])


class ManagerAccessTests(TestCase):
    def setUp(self):
        manager = get_user_model().objects.create_user("manager", password="test-password", is_staff=True)
        manager.groups.add(Group.objects.get_or_create(name="Manager")[0])
        self.client.force_login(manager)

    def test_manager_is_forbidden_from_owner_finance_and_team_urls(self):
        for name in ("store:finance_dashboard", "store:orders_csv", "store:team", "store:team_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_manager_cannot_export_or_edit_expenses_or_delete_products(self):
        expense = Expense.objects.create(date=timezone.localdate(), category="Other", title="Expense", amount=1)
        category, _ = Category.objects.get_or_create(name="Shirts")
        product = Product.objects.create(name="Manager delete test", slug="manager-delete-test", category=category, price=10, image="products/test.png")
        self.assertEqual(self.client.get(reverse("store:expenses"), {"export": "1"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("store:expense_edit", args=(expense.pk,))).status_code, 403)
        self.assertEqual(self.client.post(reverse("store:expense_delete", args=(expense.pk,))).status_code, 403)
        self.assertEqual(self.client.post(reverse("store:manage_delete", args=("products", product.pk))).status_code, 403)

    def test_manager_can_read_but_cannot_change_site_category_settings(self):
        self.assertEqual(self.client.get(reverse("store:manage_model", args=("categories",))).status_code, 200)
        self.assertEqual(self.client.post(reverse("store:manage_create", args=("categories",))).status_code, 403)

    def test_manager_order_status_updates_are_audited(self):
        order = Order.objects.create(full_name="Manager order", phone="03001234567", address="A", city="A", payment_method="cod")
        self.assertEqual(self.client.post(reverse("store:order_status_update", args=(order.pk,)), {"status": "confirmed"}).status_code, 302)
        log = OrderAuditLog.objects.get(object=order)
        self.assertEqual(log.user.username, "manager")
        self.assertIn("pending to confirmed", log.action)

    def test_manager_dashboard_and_product_editor_never_render_cost_or_profit(self):
        self.assertEqual(self.client.get(reverse("store:dashboard")).status_code, 200)
        category, _ = Category.objects.get_or_create(name="Shirts")
        product = Product.objects.create(name="Private cost test", slug="private-cost-test", category=category, price=900, cost_price=Decimal("300"), image="products/test.png")
        response = self.client.get(reverse("store:manage_edit", args=("products", product.pk)))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("cost_price", body)
        self.assertNotIn("margin", body.lower())
        self.assertNotIn("profit", body.lower())
