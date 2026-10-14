from django.core.exceptions import ValidationError
from django.db import models

from .fields import AutoSlugField, AutoSlugManager


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
    objects = AutoSlugManager()

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="subcategories", verbose_name="Category"
    )
    name = models.CharField("Name", max_length=120)
    slug = AutoSlugField(
        max_length=150, unique_scope=("category",), allow_unicode=True, db_index=False
    )
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("category", "name"), name="uniq_subcategory_name_per_category"
            ),
            models.UniqueConstraint(
                fields=("category", "slug"), name="uniq_subcategory_slug_per_category"
            ),
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class Product(TimestampedModel):
    objects = AutoSlugManager()

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
    slug = AutoSlugField(max_length=250, unique=True, allow_unicode=True, db_index=False)
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


def resolve_reference_subcategory(product, requested_id=None):
    """The subcategory whose attributes apply to a product (never guessed).

    - An explicit ``requested_id`` must be one of the product's active
      subcategories (ValueError otherwise).
    - A product with a single subcategory uses that one.
    - With several subcategories: the only one that defines active
      attributes wins; if none define any, there are no options (None);
      if several define attributes, that is ambiguous (ValueError) and
      the caller must resolve it explicitly.
    """
    subcategories = list(product.subcategories.filter(is_active=True))
    if requested_id is not None and requested_id != "":
        try:
            requested_id = int(requested_id)
        except (TypeError, ValueError):
            raise ValueError("subcategory must be a subcategory id.")
        for subcategory in subcategories:
            if subcategory.pk == requested_id:
                return subcategory
        raise ValueError("This product does not belong to the requested subcategory.")
    if len(subcategories) == 1:
        return subcategories[0]
    if not subcategories:
        return None
    with_attributes = [
        subcategory
        for subcategory in subcategories
        if subcategory.attributes.filter(is_active=True).exists()
    ]
    if not with_attributes:
        return None
    if len(with_attributes) == 1:
        return with_attributes[0]
    raise ValueError(
        "This product belongs to multiple subcategories with attributes; "
        "specify ?subcategory=<id>."
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


class ProductAttribute(TimestampedModel):
    """A generic product option defined at the subcategory level.

    All active products of a subcategory share the same attribute
    definitions (for example a "car type" select attribute and an
    independent "car model" text attribute). Attributes are managed in
    Django Admin; nothing is hardcoded per product or per key.
    """

    INPUT_SELECT = "select"
    INPUT_TEXT = "text"
    INPUT_TYPE_CHOICES = [
        (INPUT_SELECT, "Select"),
        (INPUT_TEXT, "Text"),
    ]

    subcategory = models.ForeignKey(
        Subcategory,
        on_delete=models.CASCADE,
        related_name="attributes",
        verbose_name="Subcategory",
    )
    key = models.CharField(
        "Key", max_length=64, help_text="Stable API identifier (e.g. car_type)."
    )
    name = models.CharField("Name", max_length=120, help_text="Display name (e.g. نوع خودرو).")
    input_type = models.CharField("Input type", max_length=10, choices=INPUT_TYPE_CHOICES)
    is_required = models.BooleanField("Required", default=False)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(
                fields=("subcategory", "key"), name="uniq_attribute_key_per_subcategory"
            )
        ]

    def __str__(self):
        return f"{self.subcategory} / {self.key}"


class AttributeChoice(TimestampedModel):
    """One selectable option of a `select` attribute, with its price delta.

    ``price_delta`` is added to the product's base price when a customer
    picks this choice (Toman, same convention as Product.price; the admin
    configures the amount - never business logic). Negative deltas are
    rejected at the database level.
    """

    attribute = models.ForeignKey(
        ProductAttribute,
        on_delete=models.CASCADE,
        related_name="choices",
        verbose_name="Attribute",
    )
    key = models.CharField("Key", max_length=64, help_text="Stable API identifier (e.g. offroad).")
    label = models.CharField("Label", max_length=120, help_text="Display label (e.g. آفرود).")
    price_delta = models.DecimalField("Price delta (Toman)", max_digits=12, decimal_places=0, default=0)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(
                fields=("attribute", "key"), name="uniq_choice_key_per_attribute"
            ),
            models.CheckConstraint(
                condition=models.Q(price_delta__gte=0),
                name="attribute_choice_delta_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.attribute.key}: {self.key}"

        return f"#{self.position} {self.product.name}"
