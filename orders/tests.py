import json
import shutil
import tempfile
from io import BytesIO

from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Address
from orders.models import CustomDesign, CustomDesignImage, Order
from orders.services.orders import create_order
from products.models import Category, Product

User = get_user_model()

ORDER_LIST_URL = reverse("order-list")
CUSTOM_DESIGN_URL = reverse("custom-design-order")

VALID_NATIONAL_ID = "0012345679"
VALID_NATIONAL_ID_2 = "0012345687"
PHONE = "09123456789"


def _image_file(fmt="PNG", size=(10, 10), name="design.png"):
    """A real in-memory image for multipart uploads."""
    buffer = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format=fmt)
    content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class OrderTestBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="General")
        self.product = Product.objects.create(name="Phone X", price=100000)
        self.product.categories.add(self.category)

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


class CustomDesignOrderTests(OrderTestBase):
    """POST /api/v1/orders/custom-design/ - surcharge pricing + upload security."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Keep uploaded test files out of the real media root and clean up.
        cls._media_root = tempfile.mkdtemp(prefix="mimo-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def _design_payload(self, products, quantities=None, images=None,
                        description="Print my logo, matte finish", address_id=None):
        quantities = quantities or [1] * len(products)
        data = {
            "items": json.dumps(
                [
                    {"product_id": product.pk, "quantity": quantity}
                    for product, quantity in zip(products, quantities)
                ]
            ),
            "description": description,
        }
        if images is not None:
            data["images"] = images
        if address_id:
            data["address_id"] = address_id
        return data

    def test_custom_design_order_applies_surcharge(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload(
                [self.product], [2], [_image_file()], address_id=address.pk
            ),
        )
        self.assertEqual(response.status_code, 201)
        # 100000 + 30% = 130000 per unit; x2 = 260000
        self.assertEqual(response.data["items"][0]["unit_price"], "130000")
        self.assertEqual(response.data["total_price"], "260000")
        design = response.data["custom_design"]
        self.assertEqual(design["description"], "Print my logo, matte finish")
        self.assertEqual(design["surcharge_percent"], "30.00")
        self.assertEqual(len(design["images"]), 1)
        order = Order.objects.get(pk=response.data["id"])
        image = order.custom_design.images.get(position=0)
        # Random server-generated path; user-supplied name never reaches disk.
        self.assertTrue(image.image.name.startswith("designs/"))
        self.assertTrue(image.image.name.endswith(".png"))

    def test_multiple_products_and_images(self):
        user, _ = self._make_complete_user()
        other = Product.objects.create(name="Mug", price=50000)
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload(
                [self.product, other],
                [1, 3],
                [_image_file(), _image_file(), _image_file()],
            ),
        )
        self.assertEqual(response.status_code, 201)
        # 130000 + (50000 * 1.3 * 3 = 195000) = 325000
        self.assertEqual(response.data["total_price"], "325000")
        self.assertEqual(len(response.data["custom_design"]["images"]), 3)

    def test_normal_order_response_has_no_custom_design(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["custom_design"])

    def test_requires_authentication(self):
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload([self.product], images=[_image_file()]),
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_missing_images(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL, self._design_payload([self.product], images=None)
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("images", response.data)

    def test_rejects_more_than_three_images(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload(
                [self.product], images=[_image_file() for _ in range(4)]
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("images", response.data)

    def test_rejects_non_image_content(self):
        """A text file renamed to .png is rejected by content sniffing."""
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        fake = SimpleUploadedFile("design.png", b"definitely not an image", content_type="image/png")
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload([self.product], images=[fake]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_svg_content(self):
        """SVG is an XSS vector and must never pass the format allowlist."""
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        svg = SimpleUploadedFile(
            "design.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )
        response = self.client.post(
            CUSTOM_DESIGN_URL, self._design_payload([self.product], images=[svg])
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_oversized_image(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        limit = {"CUSTOM_DESIGN": {**settings.CUSTOM_DESIGN, "MAX_IMAGE_BYTES": 10}}
        with override_settings(**limit):
            response = self.client.post(
                CUSTOM_DESIGN_URL,
                self._design_payload([self.product], images=[_image_file()]),
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_oversized_dimensions(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        limit = {"CUSTOM_DESIGN": {**settings.CUSTOM_DESIGN, "MAX_IMAGE_DIMENSION": 50}}
        with override_settings(**limit):
            response = self.client.post(
                CUSTOM_DESIGN_URL,
                self._design_payload(
                    [self.product], images=[_image_file(size=(100, 100))]
                ),
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_incomplete_profile(self):
        user = User.objects.create_user(phone_number=PHONE, national_id=VALID_NATIONAL_ID)
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload([self.product], images=[_image_file()]),
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_overlong_description(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload(
                [self.product],
                images=[_image_file()],
                description="x" * (settings.CUSTOM_DESIGN["DESCRIPTION_MAX_LENGTH"] + 1),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.data)

    def test_rejects_invalid_items_json(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            {"items": "not-json", "images": [_image_file()], "description": "ok"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.data)

    def test_inactive_product_rejected(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        self.product.is_active = False
        self.product.save()
        response = self.client.post(
            CUSTOM_DESIGN_URL,
            self._design_payload([self.product], images=[_image_file()]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
