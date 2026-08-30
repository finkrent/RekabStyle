from django.core.exceptions import ValidationError
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimestampedModel):
    name = models.CharField("Name", max_length=120, unique=True)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Subcategory(TimestampedModel):
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="subcategories", verbose_name="Category"
    )
    name = models.CharField("Name", max_length=120)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("category", "name"), name="uniq_subcategory_name_per_category"
            )
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class Product(TimestampedModel):
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products", verbose_name="Category"
    )
    subcategory = models.ForeignKey(
        Subcategory,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        verbose_name="Subcategory",
    )
    name = models.CharField("Name", max_length=200)
    description = models.TextField("Description", blank=True)
    price = models.DecimalField("Price (Toman)", max_digits=12, decimal_places=0)
    image = models.ImageField("Image", upload_to="products/", null=True, blank=True)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("is_active",))]

    def __str__(self):
        return self.name

    def clean(self):
        if self.subcategory_id and self.subcategory.category_id != self.category_id:
            raise ValidationError(
                {"subcategory": "The subcategory must belong to the selected category."}
            )


class BestSeller(models.Model):
    """A product manually curated by staff for the 'Best Sellers' showcase.

    No sales-count logic is involved: the administrator picks existing
    products in Django Admin and orders them with the `position` field
    (lower position is shown first). The storefront fetches them through
    the public /api/v1/best-sellers/ endpoint.
    """

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="best_seller",
        verbose_name="Product",
    )
    position = models.PositiveSmallIntegerField("Position", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "-created_at")  # position first; ties -> newest first
        verbose_name_plural = "best sellers"

    def __str__(self):
        return f"#{self.position} {self.product.name}"
