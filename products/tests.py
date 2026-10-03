from django.core.exceptions import ValidationError
from unittest.mock import Mock

from django.contrib import admin
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from products.admin import ProductAdminForm
from products.models import BestSeller, Category, Product, Subcategory


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