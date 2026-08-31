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
    categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="products",
        verbose_name="Categories",
        help_text="The categories this product belongs to (a product may belong to several).",
    )
    subcategories = models.ManyToManyField(
        Subcategory,
        blank=True,
        related_name="products",
        verbose_name="Subcategories",
        help_text=(
            "The subcategories this product belongs to (a product may belong "
            "to several). Each must belong to one of the product's categories."
        ),
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
        # M2M managers can only be read on saved instances; the admin form
        # passes the (not yet saved) M2M values in explicitly.
        if self.pk:
            self.validate_subcategories(self.categories.all(), self.subcategories.all())

    def validate_subcategories(self, categories=(), subcategories=()):
        """Every selected subcategory must belong to one of the product's
        selected categories.

        Usable both post-save (through ``clean()``) and pre-save with explicit
        iterables (Django Admin forms), because M2M relations cannot be read
        from an unsaved instance.
        """
        subcategories = list(subcategories)
        if not subcategories:
            return
        category_ids = {category.pk for category in categories}
        if any(subcategory.category_id not in category_ids for subcategory in subcategories):
            raise ValidationError(
                {
                    "subcategories": ValidationError(
                        "Subcategories must belong to one of the product's categories.",
                        code="invalid_subcategory",
                    )
                }
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
