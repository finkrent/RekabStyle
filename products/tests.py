from django.core.exceptions import ValidationError
from unittest.mock import Mock

from django.contrib import admin
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from products.admin import ProductAdminForm
from products.models import AttributeChoice, BestSeller, Category, Product, ProductAttribute, Subcategory


PRODUCT_LIST_URL = reverse("product-list")
CATEGORY_LIST_URL = reverse("category-list")
SUBCATEGORY_LIST_URL = reverse("subcategory-list")
BEST_SELLER_URL = reverse("best-seller-list")


class ProductApiTests(TestCase):
    """Products belong to many categories/subcategories through M2M relations."""

    def setUp(self):
        self.electronics = Category.objects.create(name="Electronics")
        self.home = Category.objects.create(name="Home & Kitchen")
        self.phones = Subcategory.objects.create(category=self.electronics, name="Mobile Phones")
        self.audio = Subcategory.objects.create(category=self.electronics, name="Audio")
        self.blenders = Subcategory.objects.create(category=self.home, name="Blenders")
        self.product = Product.objects.create(
            name="Phone X",
            description="A smart phone",
            price=25000000,
        )
        self.product.categories.add(self.electronics, self.home)
        self.product.subcategories.add(self.phones, self.blenders)
        hidden = Product.objects.create(name="Hidden Item", price=1000, is_active=False)
        hidden.categories.add(self.electronics)

    def test_product_list_is_public(self):
        response = self.client.get(PRODUCT_LIST_URL)
        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.data["results"]]
        self.assertIn("Phone X", names)
        self.assertNotIn("Hidden Item", names)

    def test_product_detail(self):
        response = self.client.get(reverse("product-detail", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["price"], "25000000")
        self.assertEqual(
            sorted(response.data["category_names"]), ["Electronics", "Home & Kitchen"]
        )
        self.assertEqual(
            sorted(response.data["subcategory_names"]), ["Blenders", "Mobile Phones"]
        )

    def test_category_filter_matches_any_category(self):
        for category in (self.electronics, self.home):
            response = self.client.get(PRODUCT_LIST_URL, {"category": category.pk})
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["name"], "Phone X")

    def test_subcategory_filter_matches_any_subcategory(self):
        for subcategory in (self.phones, self.blenders):
            response = self.client.get(PRODUCT_LIST_URL, {"subcategory": subcategory.pk})
            self.assertEqual(response.data["count"], 1)

    def test_subcategory_filter_ignores_unassigned_subcategory(self):
        # "Audio" exists but is not assigned to the product.
        response = self.client.get(PRODUCT_LIST_URL, {"subcategory": self.audio.pk})
        self.assertEqual(response.data["count"], 0)

    def test_unrelated_category_returns_nothing(self):
        other = Category.objects.create(name="Fashion")
        response = self.client.get(PRODUCT_LIST_URL, {"category": other.pk})
        self.assertEqual(response.data["count"], 0)

    def test_product_filter_and_search(self):
        Product.objects.create(name="Laptop Pro", price=50000000)
        response = self.client.get(PRODUCT_LIST_URL, {"q": "laptop"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Laptop Pro")

    def test_search_matches_description_case_insensitively_and_partially(self):
        Product.objects.create(
            name="Travel Mug", description="Insulated kitchen companion", price=5000
        )
        response = self.client.get(PRODUCT_LIST_URL, {"q": " KITCHEN "})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Travel Mug")

    def test_search_excludes_inactive_products(self):
        Product.objects.create(
            name="Hidden Laptop", description="private laptop", price=5000, is_active=False
        )
        response = self.client.get(PRODUCT_LIST_URL, {"q": "laptop"})
        self.assertEqual(response.data["count"], 0)

    def test_search_combines_with_category_filter(self):
        laptop = Product.objects.create(name="Laptop Pro", price=50000000)
        laptop.categories.add(self.home)
        response = self.client.get(
            PRODUCT_LIST_URL, {"q": "laptop", "category": self.home.pk}
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Laptop Pro")

    def test_blank_search_returns_unfiltered_active_products(self):
        response = self.client.get(PRODUCT_LIST_URL, {"q": "   "})
        self.assertEqual(response.data["count"], 1)

    def test_category_list_includes_subcategories(self):
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, 200)
        # "Electronics" sorts before "Home & Kitchen".
        subs = response.data["results"][0]["subcategories"]
        self.assertEqual(
            sorted(sub["name"] for sub in subs), ["Audio", "Mobile Phones"]
        )

    def test_category_subcategories_action(self):
        Subcategory.objects.bulk_create(
            [
                Subcategory(category=self.electronics, name=f"Accessory {index}")
                for index in range(21)
            ]
        )
        url = reverse("category-subcategories", args=[self.electronics.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 23)

    def test_subcategory_filter_by_category(self):
        Subcategory.objects.bulk_create(
            [
                Subcategory(category=self.electronics, name=f"Accessory {index}")
                for index in range(21)
            ]
        )
        response = self.client.get(SUBCATEGORY_LIST_URL, {"category": self.electronics.pk})
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 23)

    def test_validate_rejects_foreign_subcategory(self):
        fashion = Category.objects.create(name="Fashion")
        scarves = Subcategory.objects.create(category=fashion, name="Scarves")
        with self.assertRaises(ValidationError):
            self.product.validate_subcategories([self.electronics, self.home], [scarves])

    def test_validate_accepts_valid_subcategories(self):
        self.product.validate_subcategories(
            [self.electronics, self.home], [self.phones, self.blenders]
        )

    def test_clean_rejects_foreign_subcategory_on_saved_instance(self):
        fashion = Category.objects.create(name="Fashion")
        scarves = Subcategory.objects.create(category=fashion, name="Scarves")
        self.product.subcategories.add(scarves)
        with self.assertRaises(ValidationError):
            self.product.clean()


class BestSellerApiTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Electronics")
        self.phone = Product.objects.create(name="Phone X", price=1000)
        self.phone.categories.add(self.category)
        self.laptop = Product.objects.create(name="Laptop Pro", price=2000)
        self.laptop.categories.add(self.category)
        self.headphones = Product.objects.create(name="Headphones Z", price=3000)
        self.headphones.categories.add(self.category)
        self.inactive = Product.objects.create(
            name="Hidden Item", price=4000, is_active=False
        )
        self.inactive.categories.add(self.category)

    def test_best_seller_list_is_public_and_ordered_by_position(self):
        BestSeller.objects.create(product=self.laptop, position=1)
        BestSeller.objects.create(product=self.phone, position=0)
        response = self.client.get(BEST_SELLER_URL)
        self.assertEqual(response.status_code, 200)
        # Unpaginated: the response is a plain list of product objects...
        self.assertIsInstance(response.data, list)
        # ...ordered by position (lower first), regardless of insertion order.
        self.assertEqual(
            [item["name"] for item in response.data], ["Phone X", "Laptop Pro"]
        )

    def test_inactive_product_is_not_exposed(self):
        BestSeller.objects.create(product=self.inactive, position=0)
        response = self.client.get(BEST_SELLER_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_curated_products_only(self):
        BestSeller.objects.create(product=self.phone, position=0)
        response = self.client.get(BEST_SELLER_URL)
        self.assertEqual([item["name"] for item in response.data], ["Phone X"])

    def test_product_cannot_be_added_twice(self):
        BestSeller.objects.create(product=self.phone, position=0)
        with self.assertRaises(IntegrityError):
            BestSeller.objects.create(product=self.phone, position=1)


class ProductSlugTests(TestCase):
    """Products get a unique slug generated from their name."""

    def test_slug_is_generated_from_name(self):
        product = Product.objects.create(name="Phone X", price=1000)
        self.assertEqual(product.slug, "phone-x")

    def test_duplicate_names_get_unique_slugs(self):
        first = Product.objects.create(name="Phone X", price=1000)
        second = Product.objects.create(name="Phone X", price=2000)
        self.assertEqual(first.slug, "phone-x")
        self.assertEqual(second.slug, "phone-x-2")

    def test_product_detail_exposes_slug(self):
        product = Product.objects.create(name="Phone X", price=1000)
        response = self.client.get(reverse("product-detail", args=[product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], "phone-x")


class SubcategorySlugTests(TestCase):
    """Subcategory slugs are unique within their category."""

    def setUp(self):
        self.electronics = Category.objects.create(name="Electronics")
        self.home = Category.objects.create(name="Home & Kitchen")

    def test_slug_is_generated_from_name(self):
        subcategory = Subcategory.objects.create(
            category=self.electronics, name="Mobile Phones"
        )
        self.assertEqual(subcategory.slug, "mobile-phones")

    def test_same_name_in_different_categories_keeps_the_same_slug(self):
        first = Subcategory.objects.create(category=self.electronics, name="Audio")
        second = Subcategory.objects.create(category=self.home, name="Audio")
        self.assertEqual(first.slug, "audio")
        self.assertEqual(second.slug, "audio")

    def test_slug_collision_within_category_gets_suffix(self):
        first = Subcategory.objects.create(category=self.electronics, name="Audio")
        second = Subcategory.objects.create(category=self.electronics, name="AUDIO")
        self.assertEqual(first.slug, "audio")
        self.assertEqual(second.slug, "audio-2")

    def test_bulk_create_generates_slugs(self):
        Subcategory.objects.bulk_create(
            [
                Subcategory(category=self.electronics, name=f"Accessory {index}")
                for index in range(3)
            ]
        )
        slugs = list(
            Subcategory.objects.filter(category=self.electronics).values_list(
                "slug", flat=True
            )
        )
        self.assertEqual(sorted(slugs), ["accessory-0", "accessory-1", "accessory-2"])


class AdminSlugTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Electronics")

    def test_product_admin_can_set_slug(self):
        form = ProductAdminForm(
            data={
                "name": "Phone X",
                "slug": "custom-phone",
                "description": "",
                "price": "1000",
                "image": "",
                "categories": [],
                "subcategories": [],
                "is_active": "on",
            }
        )

        self.assertIn("slug", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().slug, "custom-phone")

    def test_subcategory_admin_can_set_slug(self):
        request = RequestFactory().get("/admin/")
        request.user = Mock()
        request.user.has_perm.return_value = True
        form_class = admin.site._registry[Subcategory].get_form(request)
        form = form_class(
            data={
                "name": "Audio",
                "slug": "custom-audio",
                "category": self.category.pk,
                "is_active": "on",
            }
        )

        self.assertIn("slug", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().slug, "custom-audio")


class SubcategoryDetailProductsTests(TestCase):
    """GET /subcategories/{id}/ embeds the subcategory's active products."""

    def setUp(self):
        self.category = Category.objects.create(name="Electronics")
        self.phones = Subcategory.objects.create(
            category=self.category, name="Mobile Phones"
        )
        self.phone = Product.objects.create(name="Phone X", price=25000000)
        self.phone.categories.add(self.category)
        self.phone.subcategories.add(self.phones)
        self.hidden = Product.objects.create(name="Hidden", price=1000, is_active=False)
        self.hidden.subcategories.add(self.phones)

    def test_detail_embeds_active_products(self):
        response = self.client.get(reverse("subcategory-detail", args=[self.phones.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], "mobile-phones")
        names = [item["name"] for item in response.data["products"]]
        self.assertEqual(names, ["Phone X"])

    def test_embedded_product_carries_core_fields(self):
        response = self.client.get(reverse("subcategory-detail", args=[self.phones.pk]))
        product = response.data["products"][0]
        self.assertEqual(product["slug"], "phone-x")
        self.assertEqual(product["price"], "25000000")

    def test_list_does_not_embed_products(self):
        response = self.client.get(SUBCATEGORY_LIST_URL)
        self.assertEqual(response.status_code, 200)
        for item in response.data:
            self.assertNotIn("products", item)


class ProductPaginationTests(TestCase):
    """GET /products/ pages with a fixed size of 8 and stable ordering."""

    def setUp(self):
        self.category = Category.objects.create(name="Catalog")
        self.subcategory = Subcategory.objects.create(category=self.category, name="Mats")
        for index in range(10):
            product = Product.objects.create(name=f"Product {index:02d}", price=1000 + index)
            product.categories.add(self.category)
            product.subcategories.add(self.subcategory)

    def test_page_contains_at_most_eight_products(self):
        response = self.client.get(PRODUCT_LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 10)
        self.assertEqual(len(response.data["results"]), 8)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_last_page_next_is_null(self):
        response = self.client.get(PRODUCT_LIST_URL, {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNone(response.data["next"])
        self.assertIsNotNone(response.data["previous"])

    def test_page_size_cannot_be_overridden_by_clients(self):
        response = self.client.get(PRODUCT_LIST_URL, {"page_size": 2})
        self.assertEqual(len(response.data["results"]), 8)

    def test_pages_are_stable_and_distinct(self):
        first = self.client.get(PRODUCT_LIST_URL, {"page": 1}).data["results"]
        second = self.client.get(PRODUCT_LIST_URL, {"page": 2}).data["results"]
        first_ids = [item["id"] for item in first]
        second_ids = [item["id"] for item in second]
        self.assertEqual(len(set(first_ids + second_ids)), 10)
        again = self.client.get(PRODUCT_LIST_URL, {"page": 1}).data["results"]
        self.assertEqual(first_ids, [item["id"] for item in again])

    def test_next_url_preserves_subcategory_filter(self):
        response = self.client.get(PRODUCT_LIST_URL, {"subcategory": self.subcategory.pk})
        self.assertIn(f"subcategory={self.subcategory.pk}", response.data["next"])

    def test_subcategory_filter_stays_active_on_page_two(self):
        response = self.client.get(
            PRODUCT_LIST_URL, {"subcategory": self.subcategory.pk, "page": 2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)
        for item in response.data["results"]:
            self.assertIn(self.subcategory.pk, item["subcategories"])


class ProductOptionTests(TestCase):
    """GET /products/{id}/ exposes the reference subcategory's attributes."""

    def setUp(self):
        self.category = Category.objects.create(name="Auto")
        self.mats = Subcategory.objects.create(category=self.category, name="Floor Mats")
        self.covers = Subcategory.objects.create(category=self.category, name="Covers")
        self.product = Product.objects.create(name="Mat X", price=1000000)
        self.product.categories.add(self.category)
        self.product.subcategories.add(self.mats, self.covers)

        self.car_type = ProductAttribute.objects.create(
            subcategory=self.mats,
            key="car_type",
            name="نوع خودرو",
            input_type=ProductAttribute.INPUT_SELECT,
            is_required=True,
        )
        self.sedan = AttributeChoice.objects.create(
            attribute=self.car_type, key="sedan", label="سواری", price_delta=0
        )
        self.offroad = AttributeChoice.objects.create(
            attribute=self.car_type, key="offroad", label="آفرود", price_delta=200000
        )
        self.car_model = ProductAttribute.objects.create(
            subcategory=self.mats,
            key="car_model",
            name="مدل خودرو",
            input_type=ProductAttribute.INPUT_TEXT,
            is_required=True,
        )
        self.piece_count = ProductAttribute.objects.create(
            subcategory=self.mats,
            key="piece_count",
            name="تعداد تکه",
            input_type=ProductAttribute.INPUT_SELECT,
            is_required=False,
        )
        AttributeChoice.objects.create(
            attribute=self.piece_count, key="two_piece", label="۲ تکه", price_delta=0
        )
        self.hidden = ProductAttribute.objects.create(
            subcategory=self.mats,
            key="legacy",
            name="Legacy",
            input_type=ProductAttribute.INPUT_TEXT,
            is_active=False,
        )

    def _detail(self, **params):
        return self.client.get(reverse("product-detail", args=[self.product.pk]), params)

    def test_options_include_select_and_text_attributes_together(self):
        response = self._detail(subcategory=self.mats.pk)
        self.assertEqual(response.status_code, 200)
        options = {option["key"]: option for option in response.data["options"]}
        self.assertEqual(set(options), {"car_type", "car_model", "piece_count"})

        car_type = options["car_type"]
        self.assertEqual(car_type["type"], "select")
        self.assertTrue(car_type["required"])
        self.assertNotIn("price_delta", car_type)
        self.assertEqual(
            [(choice["key"], choice["price_delta"]) for choice in car_type["choices"]],
            [("sedan", "0"), ("offroad", "200000")],
        )

        car_model = options["car_model"]
        self.assertEqual(car_model["type"], "text")
        self.assertTrue(car_model["required"])
        self.assertEqual(car_model["price_delta"], "0")
        self.assertNotIn("choices", car_model)

        self.assertFalse(options["piece_count"]["required"])

    def test_inactive_attributes_are_not_returned(self):
        response = self._detail(subcategory=self.mats.pk)
        keys = [option["key"] for option in response.data["options"]]
        self.assertNotIn("legacy", keys)

    def test_explicit_reference_subcategory_is_used(self):
        response = self._detail(subcategory=self.covers.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["options"], [])

    def test_foreign_subcategory_is_rejected(self):
        foreign = Subcategory.objects.create(category=self.category, name="Other")
        response = self._detail(subcategory=foreign.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("subcategory", response.data)

    def test_invalid_subcategory_value_is_rejected(self):
        response = self._detail(subcategory="abc")
        self.assertEqual(response.status_code, 400)
        self.assertIn("subcategory", response.data)