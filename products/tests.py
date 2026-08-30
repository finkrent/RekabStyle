from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from products.models import BestSeller, Category, Product, Subcategory


PRODUCT_LIST_URL = reverse("product-list")
CATEGORY_LIST_URL = reverse("category-list")
SUBCATEGORY_LIST_URL = reverse("subcategory-list")
BEST_SELLER_URL = reverse("best-seller-list")


class ProductApiTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Electronics")
        self.subcategory = Subcategory.objects.create(
            category=self.category, name="Mobile Phones"
        )
        self.product = Product.objects.create(
            name="Phone X",
            description="A smart phone",
            price=25000000,
            category=self.category,
            subcategory=self.subcategory,
        )
        Product.objects.create(
            name="Hidden Item", price=1000, category=self.category, is_active=False
        )

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
        self.assertEqual(response.data["category_name"], "Electronics")
        self.assertEqual(response.data["subcategory_name"], "Mobile Phones")

    def test_product_filter_and_search(self):
        response = self.client.get(PRODUCT_LIST_URL, {"category": self.category.pk})
        self.assertEqual(response.data["count"], 1)

        Product.objects.create(
            name="Laptop Pro", price=50000000, category=self.category
        )
        response = self.client.get(PRODUCT_LIST_URL, {"search": "laptop"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Laptop Pro")

    def test_category_list_includes_subcategories(self):
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, 200)
        subs = response.data["results"][0]["subcategories"]
        self.assertEqual(subs[0]["name"], "Mobile Phones")

    def test_category_subcategories_action(self):
        url = reverse("category-subcategories", args=[self.category.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_subcategory_filter_by_category(self):
        response = self.client.get(SUBCATEGORY_LIST_URL, {"category": self.category.pk})
        self.assertEqual(response.data["count"], 1)


class BestSellerApiTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Electronics")
        self.phone = Product.objects.create(
            name="Phone X", price=1000, category=self.category
        )
        self.laptop = Product.objects.create(
            name="Laptop Pro", price=2000, category=self.category
        )
        self.headphones = Product.objects.create(
            name="Headphones Z", price=3000, category=self.category
        )
        self.inactive = Product.objects.create(
            name="Hidden Item", price=4000, category=self.category, is_active=False
        )

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
