import json
import shutil
import tempfile
from io import BytesIO
from unittest import mock

from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Address
from orders.models import CustomDesign, Order, OrderItemOption
from orders.services.orders import create_order
from payments.services.payments import initiate_payment
from products.models import AttributeChoice, Category, Product, ProductAttribute, Subcategory

User = get_user_model()

ORDER_LIST_URL = reverse("order-list")

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


class CheckoutCustomDesignTests(OrderTestBase):
    """POST /api/v1/orders/ with the "Custom Design" checkbox flow.

    The checkbox lives on the checkout page: when checked, the customer picks
    some of the submitted items for the custom-design list, writes a
    description and uploads 1-3 images. Selected items are priced +30%; the
    rest stay at the catalog price. Everything lands in one request, so the
    price snapshot is correct from the start.
    """

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

    def _checkout_payload(self, products, quantities=None, custom_product_ids=None,
                          description=None, images=None, address_id=None):
        quantities = quantities or [1] * len(products)
        data = {
            "items": json.dumps(
                [
                    {"product_id": product.pk, "quantity": quantity}
                    for product, quantity in zip(products, quantities)
                ]
            ),
        }
        if custom_product_ids is not None:
            data["custom_design_product_ids"] = json.dumps(custom_product_ids)
        if description is not None:
            data["custom_design_description"] = description
        if images is not None:
            data["images"] = images
        if address_id:
            data["address_id"] = address_id
        return data

    def test_surcharge_applies_only_to_selected_items(self):
        user, address = self._make_complete_user()
        other = Product.objects.create(name="Mug", price=50000)
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product, other],
                [2, 1],
                custom_product_ids=[self.product.pk],
                description="Print my logo, matte finish",
                images=[_image_file()],
                address_id=address.pk,
            ),
        )
        self.assertEqual(response.status_code, 201)
        items = response.data["items"]
        # Phone X is custom: 100000 + 30% = 130000 (x2); Mug stays 50000.
        self.assertEqual(items[0]["unit_price"], "130000")
        self.assertEqual(items[0]["surcharge_percent"], "30.00")
        self.assertEqual(items[1]["unit_price"], "50000")
        self.assertEqual(items[1]["surcharge_percent"], "0.00")
        self.assertEqual(response.data["total_price"], "310000")
        design = response.data["custom_design"]
        self.assertEqual(design["description"], "Print my logo, matte finish")
        self.assertEqual(design["surcharge_percent"], "30.00")
        self.assertEqual(design["status"], "pending")
        self.assertEqual(design["order_items"], [items[0]["id"]])
        self.assertEqual(len(design["images"]), 1)
        order = Order.objects.get(pk=response.data["id"])
        image = order.custom_design.images.get(position=0)
        # Random server-generated path; user-supplied name never reaches disk.
        self.assertTrue(image.image.name.startswith("designs/"))
        self.assertTrue(image.image.name.endswith(".png"))

    def test_multipart_plain_order_without_design(self):
        """Multipart body without design fields behaves like a plain order."""
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload([self.product], [2], address_id=address.pk),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_price"], "200000")
        self.assertIsNone(response.data["custom_design"])
        self.assertEqual(response.data["items"][0]["surcharge_percent"], "0.00")

    def test_json_plain_order_response_has_no_custom_design(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {"items": [{"product_id": self.product.pk, "quantity": 1}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["custom_design"])

    def test_all_items_custom(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                [2],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 201)
        # 100000 * 1.3 = 130000 x2 = 260000
        self.assertEqual(response.data["total_price"], "260000")
        self.assertEqual(len(response.data["custom_design"]["order_items"]), 1)

    def test_design_fields_without_selection_rejected(self):
        """Images/description without a selection are a 400 (no silent no-op)."""
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload([self.product], images=[_image_file()]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_design_product_ids", response.data)
        self.assertFalse(Order.objects.exists())

    def test_selection_requires_description(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_design_description", response.data)
        self.assertFalse(Order.objects.exists())

    def test_selection_requires_images(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("images", response.data)
        self.assertFalse(Order.objects.exists())

    def test_custom_ids_must_be_subset_of_items(self):
        user, _ = self._make_complete_user()
        other = Product.objects.create(name="Mug", price=50000)
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk, other.pk],
                description="Print my logo",
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_design_product_ids", response.data)
        self.assertFalse(Order.objects.exists())

    def test_requires_authentication(self):
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_more_than_three_images(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[_image_file() for _ in range(4)],
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
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[fake],
            ),
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
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[svg],
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_oversized_image(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        limit = {"CUSTOM_DESIGN": {**settings.CUSTOM_DESIGN, "MAX_IMAGE_BYTES": 10}}
        with override_settings(**limit):
            response = self.client.post(
                ORDER_LIST_URL,
                self._checkout_payload(
                    [self.product],
                    custom_product_ids=[self.product.pk],
                    description="Print my logo",
                    images=[_image_file()],
                ),
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_oversized_dimensions(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        limit = {"CUSTOM_DESIGN": {**settings.CUSTOM_DESIGN, "MAX_IMAGE_DIMENSION": 50}}
        with override_settings(**limit):
            response = self.client.post(
                ORDER_LIST_URL,
                self._checkout_payload(
                    [self.product],
                    custom_product_ids=[self.product.pk],
                    description="Print my logo",
                    images=[_image_file(size=(100, 100))],
                ),
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_rejects_incomplete_profile(self):
        user = User.objects.create_user(phone_number=PHONE, national_id=VALID_NATIONAL_ID)
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_overlong_description(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="x" * (settings.CUSTOM_DESIGN["DESCRIPTION_MAX_LENGTH"] + 1),
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("custom_design_description", response.data)

    def test_rejects_invalid_items_json(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        response = self.client.post(
            ORDER_LIST_URL,
            {
                "items": "not-json",
                "custom_design_product_ids": json.dumps([1]),
                "custom_design_description": "ok",
                "images": [_image_file()],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.data)

    def test_inactive_product_rejected(self):
        user, _ = self._make_complete_user()
        self.client.force_login(user)
        self.product.is_active = False
        self.product.save()
        response = self.client.post(
            ORDER_LIST_URL,
            self._checkout_payload(
                [self.product],
                custom_product_ids=[self.product.pk],
                description="Print my logo",
                images=[_image_file()],
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())


class OrderUpdateTests(OrderTestBase):
    """PATCH /api/v1/orders/{id}/ - replace a pending order's items (cart-sync)."""

    def _url(self, order):
        return reverse("order-detail", args=[order.pk])

    def _patch(self, order, items):
        return self.client.patch(
            self._url(order),
            {"items": items},
            content_type="application/json",
        )

    def test_owner_can_add_and_change_items(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        other = Product.objects.create(name="Charger", price=50000)
        other.categories.add(self.category)
        self.client.force_login(user)
        response = self._patch(
            order,
            [
                {"product_id": self.product.pk, "quantity": 1},
                {"product_id": other.pk, "quantity": 3},
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_price"], "250000")
        self.assertEqual(response.data["status"], Order.STATUS_PENDING)
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 2)
        quantities = {item.product_id: item.quantity for item in order.items.all()}
        self.assertEqual(quantities, {self.product.pk: 1, other.pk: 3})

    def test_item_omitted_from_payload_is_removed(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        other = Product.objects.create(name="Case", price=5000)
        other.categories.add(self.category)
        self.client.force_login(user)
        response = self._patch(order, [{"product_id": other.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.get().product_id, other.pk)
        self.assertEqual(order.total_price, 5000)

    def test_patched_items_use_current_product_price(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)  # snapshotted at 100000
        self.product.price = 120000
        self.product.save()
        self.client.force_login(user)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        item = order.items.get()
        self.assertEqual(item.unit_price, 120000)
        self.assertEqual(order.total_price, 120000)

    def test_non_pending_order_cannot_be_patched(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        order.status = Order.STATUS_PAID
        order.save()
        self.client.force_login(user)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 5}])
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.items.get().quantity, 2)

    def test_order_with_custom_design_cannot_be_patched(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        design = CustomDesign.objects.create(order=order, description="Print my logo")
        design.order_items.set(order.items.all())
        self.client.force_login(user)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 400)

    def test_other_users_order_returns_404(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address)
        other_user, _ = self._make_complete_user(
            phone_number="09123456788", national_id=VALID_NATIONAL_ID_2
        )
        self.client.force_login(other_user)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_returns_401(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 401)

    def test_inactive_product_rejected_and_order_unchanged(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        self.product.is_active = False
        self.product.save()
        self.client.force_login(user)
        response = self._patch(order, [{"product_id": self.product.pk, "quantity": 1}])
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.total_price, 200000)

    def test_empty_items_rejected(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        self.client.force_login(user)
        response = self._patch(order, [])
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.data)
        order.refresh_from_db()
        self.assertEqual(order.items.count(), 1)

    def test_invalid_items_json_rejected(self):
        user, address = self._make_complete_user()
        order = self._create_order(user, address, quantity=2)
        self.client.force_login(user)
        response = self._patch(order, "not-json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.data)


class OrderOptionsTests(OrderTestBase):
    """POST /api/v1/orders/ with subcategory attributes and selected options."""

    def setUp(self):
        super().setUp()
        self.subcategory = Subcategory.objects.create(
            category=self.category, name="Floor Mats"
        )
        self.product.subcategories.add(self.subcategory)
        self.car_type = ProductAttribute.objects.create(
            subcategory=self.subcategory,
            key="car_type",
            name="Car type",
            input_type=ProductAttribute.INPUT_SELECT,
            is_required=True,
        )
        self.sedan = AttributeChoice.objects.create(
            attribute=self.car_type, key="sedan", label="Sedan", price_delta=0
        )
        self.offroad = AttributeChoice.objects.create(
            attribute=self.car_type, key="offroad", label="Offroad", price_delta=200000
        )
        self.car_model = ProductAttribute.objects.create(
            subcategory=self.subcategory,
            key="car_model",
            name="Car model",
            input_type=ProductAttribute.INPUT_TEXT,
            is_required=True,
        )
        self.piece_count = ProductAttribute.objects.create(
            subcategory=self.subcategory,
            key="piece_count",
            name="Piece count",
            input_type=ProductAttribute.INPUT_SELECT,
            is_required=False,
        )
        self.four_piece = AttributeChoice.objects.create(
            attribute=self.piece_count, key="four_piece", label="4", price_delta=300000
        )

    def _item(self, options=None, quantity=1, with_subcategory=True):
        item = {"product_id": self.product.pk, "quantity": quantity}
        if with_subcategory:
            item["subcategory_id"] = self.subcategory.pk
        if options is not None:
            item["selected_options"] = options
        return item

    def _checkout(self, items):
        return self.client.post(
            ORDER_LIST_URL, {"items": items}, content_type="application/json"
        )

    def _valid_options(self):
        return [
            {"option_id": self.car_type.pk, "choice_id": self.offroad.pk},
            {"option_id": self.car_model.pk, "value": "Peugeot 207"},
        ]

    def test_valid_select_and_text_options_are_accepted_and_priced(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": self.piece_count.pk, "choice_id": self.four_piece.pk}
        ]
        response = self._checkout([self._item(options, quantity=2)])
        self.assertEqual(response.status_code, 201)
        # 100000 base + 200000 offroad + 300000 four-piece = 600000 per unit
        self.assertEqual(response.data["items"][0]["unit_price"], "600000")
        self.assertEqual(response.data["items"][0]["total_price"], "1200000")
        self.assertEqual(response.data["total_price"], "1200000")
        saved = {opt["attribute_key"]: opt for opt in response.data["items"][0]["options"]}
        self.assertEqual(set(saved), {"car_type", "car_model", "piece_count"})
        self.assertEqual(saved["car_type"]["choice_key"], "offroad")
        self.assertEqual(saved["car_type"]["price_delta"], "200000")
        self.assertEqual(saved["car_model"]["text_value"], "Peugeot 207")
        self.assertEqual(saved["car_model"]["price_delta"], "0")

    def test_missing_required_select_attribute_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [{"option_id": self.car_model.pk, "value": "Peugeot 207"}]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_missing_required_text_attribute_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [{"option_id": self.car_type.pk, "choice_id": self.sedan.pk}]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_invalid_choice_id_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": self.piece_count.pk, "choice_id": 999999}
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_attribute_from_another_subcategory_rejected(self):
        other = Subcategory.objects.create(category=self.category, name="Covers")
        foreign_attribute = ProductAttribute.objects.create(
            subcategory=other,
            key="color",
            name="Color",
            input_type=ProductAttribute.INPUT_SELECT,
            is_required=False,
        )
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": foreign_attribute.pk, "choice_id": 1}
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_inactive_attribute_rejected(self):
        self.car_model.is_active = False
        self.car_model.save()
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self._checkout([self._item(self._valid_options())])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_duplicate_attribute_submission_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": self.car_type.pk, "choice_id": self.sedan.pk}
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_optional_attribute_can_be_omitted(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self._checkout([self._item(self._valid_options())])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_price"], "300000")

    def test_zero_cost_choice_works(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [
            {"option_id": self.car_type.pk, "choice_id": self.sedan.pk},
            {"option_id": self.car_model.pk, "value": "Peugeot 207"},
        ]
        response = self._checkout([self._item(options, quantity=2)])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["items"][0]["unit_price"], "100000")
        self.assertEqual(response.data["total_price"], "200000")

    def test_select_attribute_rejects_text_value(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [
            {"option_id": self.car_type.pk, "value": "anything"},
            {"option_id": self.car_model.pk, "value": "Peugeot 207"},
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)

    def test_text_attribute_rejects_choice_id(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [
            {"option_id": self.car_type.pk, "choice_id": self.sedan.pk},
            {"option_id": self.car_model.pk, "choice_id": self.sedan.pk},
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)

    def test_unexpected_option_fields_rejected(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": self.piece_count.pk, "choice_id": self.four_piece.pk, "price_delta": 1}
        ]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)

    def test_client_supplied_item_price_is_ignored(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        item = self._item(self._valid_options())
        item["price"] = 1
        item["unit_price"] = 1
        response = self._checkout([item])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["items"][0]["unit_price"], "300000")

    def test_subcategory_membership_is_enforced(self):
        other = Subcategory.objects.create(category=self.category, name="Covers")
        user, address = self._make_complete_user()
        self.client.force_login(user)
        item = self._item(self._valid_options())
        item["subcategory_id"] = other.pk
        response = self._checkout([item])
        self.assertEqual(response.status_code, 400)

    def test_inactive_subcategory_id_rejected(self):
        retired = Subcategory.objects.create(
            category=self.category, name="Retired", is_active=False
        )
        self.product.subcategories.add(retired)
        user, address = self._make_complete_user()
        self.client.force_login(user)
        item = self._item(self._valid_options())
        item["subcategory_id"] = retired.pk
        response = self._checkout([item])
        self.assertEqual(response.status_code, 400)
        self.assertIn("subcategory_id", response.data["items"][0])

    def test_multi_subcategory_options_require_reference(self):
        other = Subcategory.objects.create(category=self.category, name="Covers")
        self.product.subcategories.add(other)
        # Both subcategories define attributes -> ambiguous, never guessed.
        ProductAttribute.objects.create(
            subcategory=other,
            key="color",
            name="Color",
            input_type=ProductAttribute.INPUT_TEXT,
            is_required=False,
        )
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self._checkout([self._item(self._valid_options(), with_subcategory=False)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())

    def test_option_snapshots_survive_definition_changes(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        response = self._checkout([self._item(self._valid_options())])
        self.assertEqual(response.status_code, 201)
        order_id = response.data["id"]

        self.car_type.name = "Vehicle type"
        self.car_type.is_active = False
        self.car_type.save()
        self.offroad.label = "4x4"
        self.offroad.price_delta = 999999
        self.offroad.save()
        self.car_model.name = "Model"
        self.car_model.save()

        detail = self.client.get(reverse("order-detail", args=[order_id]))
        self.assertEqual(detail.status_code, 200)
        saved = {opt["attribute_key"]: opt for opt in detail.data["items"][0]["options"]}
        self.assertEqual(saved["car_type"]["attribute_label"], "Car type")
        self.assertEqual(saved["car_type"]["choice_label"], "Offroad")
        self.assertEqual(saved["car_type"]["price_delta"], "200000")
        self.assertEqual(saved["car_model"]["attribute_label"], "Car model")
        self.assertEqual(saved["car_model"]["text_value"], "Peugeot 207")
        self.assertEqual(saved["car_model"]["price_delta"], "0")

    def test_failed_validation_creates_no_partial_order(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = [{"option_id": self.car_type.pk, "choice_id": self.offroad.pk}]
        response = self._checkout([self._item(options)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.filter(user=user).exists())
        self.assertEqual(OrderItemOption.objects.count(), 0)

    def test_payment_initiate_uses_backend_calculated_total(self):
        user, address = self._make_complete_user()
        self.client.force_login(user)
        options = self._valid_options() + [
            {"option_id": self.piece_count.pk, "choice_id": self.four_piece.pk}
        ]
        response = self._checkout([self._item(options)])
        order = Order.objects.get(pk=response.data["id"])
        with mock.patch(
            "payments.services.payments.request_payment", return_value="TRACK123"
        ) as mocked:
            payment = initiate_payment(order, "http://testserver/api/v1/payments/callback/")
        self.assertEqual(payment.amount, order.total_price)
        self.assertEqual(mocked.call_args.kwargs["amount"], order.total_price)

