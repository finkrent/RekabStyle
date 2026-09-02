import secrets
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone

from products.models import Product


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_PROCESSING = "processing"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    order_number = models.CharField(
        "Order number", max_length=20, unique=True, editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(
        "Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    total_price = models.DecimalField(
        "Total price (Toman)", max_digits=14, decimal_places=0, default=0
    )
    shipping_address = models.TextField("Shipping address", blank=True)
    shipping_postal_code = models.CharField("Shipping postal code", max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_order_number():
        return f"{timezone.now():%Y%m%d}-{secrets.token_hex(4).upper()}"


class OrderItem(models.Model):
    """A line item that preserves the product name and price at purchase time.

    ``surcharge_percent`` freezes the custom-design surcharge that applied to
    this line at purchase time (0 for regular items), so the snapshot stays
    correct even if the global surcharge setting changes later.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField("Product name", max_length=200)
    unit_price = models.DecimalField("Unit price (Toman)", max_digits=12, decimal_places=0)
    quantity = models.PositiveIntegerField("Quantity", default=1)
    surcharge_percent = models.DecimalField(
        "Custom-design surcharge %", max_digits=5, decimal_places=2, default=Decimal("0")
    )
    total_price = models.DecimalField("Total price (Toman)", max_digits=14, decimal_places=0)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)


def design_image_path(instance, filename):
    """Random storage path under designs/YYYY/MM/.

    The user-supplied filename and directory structure never reach the disk;
    only the extension is kept (the extension itself is decided server-side
    by the re-encoding step, never trusted from the client).
    """
    extension = Path(filename).suffix.lower() or ".png"
    return f"designs/{timezone.now():%Y/%m}/{uuid4().hex}{extension}"


class CustomDesign(models.Model):
    """A customer's custom-design request attached to an order.

    Created at checkout through POST /api/v1/orders/ (the customer checks
    "Custom Design" on the order page, picks some of his order items, and
    supplies a description + 1-3 images). Selected line items are priced at
    the product price plus ``surcharge_percent`` (30% by default) and the
    images + description are stored here so staff know what to produce.

    ``status`` exists for the future designer-review workflow (Pending ->
    In Review -> Approved/Rejected -> Completed); nothing sets it yet besides
    the default.
    """

    STATUS_PENDING = "pending"
    STATUS_IN_REVIEW = "in_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_REVIEW, "In Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_COMPLETED, "Completed"),
    ]

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="custom_design"
    )
    order_items = models.ManyToManyField(
        OrderItem,
        related_name="custom_designs",
        verbose_name="Customized order items",
        help_text="The order items this design applies to (each carries the surcharge).",
    )
    description = models.TextField("Description")
    surcharge_percent = models.DecimalField(
        "Surcharge %", max_digits=5, decimal_places=2, default=Decimal("30")
    )
    status = models.CharField(
        "Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Custom design for {self.order.order_number}"


class CustomDesignImage(models.Model):
    """One uploaded design image (1-3 per custom-design order)."""

    design = models.ForeignKey(
        CustomDesign, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField("Image", upload_to=design_image_path)
    position = models.PositiveSmallIntegerField("Position", default=0)

    class Meta:
        ordering = ("position", "id")

    def __str__(self):
        return f"Image #{self.position} of {self.design}"
