"""Order creation business logic (checkout validation, price snapshot)."""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from accounts.models import Address
from orders.models import CustomDesign, CustomDesignImage, Order, OrderItem
from products.models import Product

# The custom-design surcharge applied on top of every product's price
# (see settings.CUSTOM_DESIGN). Also stored per order for auditability.
CUSTOM_DESIGN_SURCHARGE = Decimal(str(settings.CUSTOM_DESIGN["SURCHARGE_PERCENT"]))


class OrderError(Exception):
    """Raised when an order cannot be created. Message is user-facing."""


def create_order(user, items, address):
    """Create an order atomically.

    `items` is a list of {"product": <Product>, "quantity": int}.
    `address` is the Address instance to ship to; its text and postal code are
    snapshotted onto the order so later address edits do not affect it.
    """
    if not isinstance(address, Address):
        raise OrderError("Please add an address before placing an order.")
    if not user.profile_is_complete:
        raise OrderError("Please complete your profile before placing an order.")
    if not items:
        raise OrderError("An order must contain at least one item.")

    with transaction.atomic():
        order = Order.objects.create(
            user=user,
            shipping_address=address.address,
            shipping_postal_code=address.postal_code,
        )
        total = Decimal("0")
        for item in items:
            product = Product.objects.select_for_update().get(pk=item["product"].pk)
            if not product.is_active:
                raise OrderError(f"Product '{product.name}' is not available.")
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit_price=product.price,
                quantity=item["quantity"],
            )
            total += order_item.total_price
        order.total_price = total
        order.save(update_fields=["total_price"])
    return order


def create_custom_design_order(user, items, address, description, images):
    """Create a custom-design order atomically.

    Same validation and snapshotting as ``create_order``, but every unit
    price carries the custom-design surcharge (30% by default, rounded to
    whole Toman) and the design description plus validated, re-encoded
    images are attached to the order for staff.

    ``items`` is a list of {"product": <Product>, "quantity": int}.
    ``images`` is a list of ``(bytes, extension)`` tuples produced by
    ``orders.services.design_uploads.validate_and_reencode``.
    """
    if not isinstance(address, Address):
        raise OrderError("Please add an address before placing an order.")
    if not user.profile_is_complete:
        raise OrderError("Please complete your profile before placing an order.")
    if not items:
        raise OrderError("An order must contain at least one item.")
    if not images:
        raise OrderError("Please upload at least one design image.")

    with transaction.atomic():
        order = Order.objects.create(
            user=user,
            shipping_address=address.address,
            shipping_postal_code=address.postal_code,
        )
        multiplier = 1 + CUSTOM_DESIGN_SURCHARGE / Decimal("100")
        total = Decimal("0")
        for item in items:
            product = Product.objects.select_for_update().get(pk=item["product"].pk)
            if not product.is_active:
                raise OrderError(f"Product '{product.name}' is not available.")
            unit_price = (product.price * multiplier).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit_price=unit_price,
                quantity=item["quantity"],
            )
            total += order_item.total_price
        order.total_price = total
        order.save(update_fields=["total_price"])

        design = CustomDesign.objects.create(
            order=order,
            description=description,
            surcharge_percent=CUSTOM_DESIGN_SURCHARGE,
        )
        for position, (data, extension) in enumerate(images):
            CustomDesignImage.objects.create(
                design=design,
                position=position,
                # upload_to (design_image_path) turns this into a random
                # designs/YYYY/MM/<uuid><ext> path on the storage.
                image=ContentFile(data, name=f"design{extension}"),
            )
    return order
