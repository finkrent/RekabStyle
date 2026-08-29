from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Address
from orders.models import Order
from orders.services.orders import create_order
from products.models import Category, Product

User = get_user_model()

ORDER_LIST_URL = reverse("order-list")

VALID_NATIONAL_ID = "0012345679"
VALID_NATIONAL_ID_2 = "0012345687"
PHONE = "09123456789"


class OrderTestBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="General")
        self.product = Product.objects.create(
            name="Phone X", price=100000, category=self.category
        )

    def _make_complete_user(self, phone_number="09123456789", national_id=VALID_NATIONAL_ID):
        """A user whose profile passes the checkout gate, with one address."""
        user = User.objects.create_user(
            phone_number=phone_number,
            national_id=national_id,
            first_name="Ali",
            last_name="Rezaei",
        )
        address = Address.objects.create(
            user=user, address="Tehran, Vanak St. 1", postal_code="1234567890"
        )
        return user, address

    def _create_order(self, user, address, quantity=2):
        return create_order(
            user,
            items=[{"product": self.product, "quantity": quantity}],
            address=address,
        )


class OrderCreateTests(OrderTestBase):
    def test_authenticated_user_can_create_order(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {
                "items": [{"product_id": self.product.pk, "quantity": 2}],
                "address_id": address.pk,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_price"], "200000")
        self.assertEqual(response.data["shipping_postal_code"], "1234567890")
        order = Order.objects.get(pk=response.data["id"])
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(order.shipping_address, "Tehran, Vanak St. 1")

    def test_order_uses_latest_address_by_default(self):
        user, address = self._make_complete_user()
        newest = Address.objects.create(
            user=user, address="Tehran, Niavaran St. 2", postal_code="1111111111"
        )
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["shipping_address"], "Tehran, Niavaran St. 2")
        self.assertEqual(newest.postal_code, "1111111111")

    def test_order_without_any_address_rejected(self):
        user = User.objects.create_user(
            phone_number=PHONE,
            national_id=VALID_NATIONAL_ID,
            first_name="Ali",
            last_name="Rezaei",
        )
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("address", response.data["detail"])

    def test_cannot_use_another_users_address(self):
        user, _address = self._make_complete_user()
        other_user, other_address = self._make_complete_user(
            "09120000001", VALID_NATIONAL_ID_2
        )
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {
                "items": [{"product_id": self.product.pk, "quantity": 1}],
                "address_id": other_address.pk,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_order_preserves_purchase_time_price(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address)
        self.product.price = 999999
        self.product.save()
        item = order.items.first()
        self.assertEqual(item.unit_price, 100000)
        self.assertEqual(order.total_price, 200000)

    def test_incomplete_profile_cannot_checkout(self):
        # Has an address, but the profile itself is incomplete (no national ID/names).
        user = User.objects.create_user(phone_number=PHONE, first_name="Ali")
        Address.objects.create(user=user, address="Tehran", postal_code="1234567890")
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data["detail"])
        self.assertEqual(Order.objects.count(), 0)

    def test_anonymous_cannot_create_order(self):
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_product_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        self.product.is_active = False
        self.product.save()
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class OrderVisibilityTests(OrderTestBase):
    def test_user_sees_only_own_orders(self):
        user, address = self._make_complete_user()
        other, other_address = self._make_complete_user("09120000001", VALID_NATIONAL_ID_2)
        self._create_order(user, address)
        self._create_order(other, other_address)

        self.client.force_login(user)
        response = self.client.get(ORDER_LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_user_cannot_access_another_users_order(self):
        user, _address = self._make_complete_user()
        other, other_address = self._make_complete_user("09120000001", VALID_NATIONAL_ID_2)
        order = self._create_order(other, other_address)

        self.client.force_login(user)
        response = self.client.get(reverse("order-detail", args=[order.pk]))
        self.assertEqual(response.status_code, 404)

    def test_admin_sees_all_orders(self):
        user, address = self._make_complete_user()
        other, other_address = self._make_complete_user("09120000001", VALID_NATIONAL_ID_2)
        self._create_order(user, address)
        self._create_order(other, other_address)

        admin = User.objects.create_superuser(
            phone_number="09111111111", password="admin-pass-123"
        )
        self.client.force_login(admin)
        response = self.client.get(ORDER_LIST_URL)
        self.assertEqual(response.data["count"], 2)

    def test_admin_detail_includes_customer_and_shipping_information(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address)

        admin = User.objects.create_superuser(
            phone_number="09111111111", password="admin-pass-123"
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("order-detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["customer_phone_number"], "09123456789")
        self.assertEqual(response.data["customer_national_id"], VALID_NATIONAL_ID)
        self.assertEqual(response.data["customer_first_name"], "Ali")
        self.assertEqual(response.data["customer_last_name"], "Rezaei")
        self.assertEqual(response.data["shipping_address"], "Tehran, Vanak St. 1")
        self.assertEqual(response.data["shipping_postal_code"], "1234567890")

    def test_user_detail_hides_sensitive_customer_information(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address)

        self.client.force_login(user)
        response = self.client.get(reverse("order-detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        for field in (
            "customer_phone_number",
            "customer_national_id",
            "customer_first_name",
            "customer_last_name",
        ):
            self.assertNotIn(field, response.data)
