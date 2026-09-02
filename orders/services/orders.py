"""Order creation business logic (checkout validation, price snapshot)."""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from accounts.models import Address
from orders.models import CustomDesign, CustomDesignImage, Order, OrderItem
from products.models import Product

# The custom-design surcharge applied on top of selected products' prices
# (see settings.CUSTOM_DESIGN). Also stored per order item and per design
# for auditability.
CUSTOM_DESIGN_SURCHARGE = Decimal(str(settings.CUSTOM_DESIGN["SURCHARGE_PERCENT"]))


class OrderError(Exception):
    """Raised when an order cannot be created. Message is user-facing."""


def create_order(user, items, address, design=None):
    """Create an order atomically.

    `items` is a list of {"product": <Product>, "quantity": int}.
    `address` is the Address instance to ship to; its text and postal code are
    snapshotted onto the order so later address edits do not affect it.

    `design` (optional) activates the custom-design flow selected on the
    checkout page: {"product_ids": [int], "description": str,
    "images": [(bytes, extension), ...]} where the images are the validated,
    re-encoded buffers produced by
    ``orders.services.design_uploads.validate_and_reencode``. Every item
    whose product id is listed is priced at price * (1 + surcharge), the
    surcharge is frozen onto the OrderItem, and a ``CustomDesign`` with its
    images and linked order items is created in the same transaction.
    """
    if not isinstance(address, Address):
        raise OrderError("Please add an address before placing an order.")
    if not user.profile_is_complete:
        raise OrderError("Please complete your profile before placing an order.")
    if not items:
        raise OrderError("An order must contain at least one item.")

    design_product_ids = set(design["product_ids"]) if design else set()

    with transaction.atomic():
        order = Order.objects.create(
            user=user,
            shipping_address=address.address,
            shipping_postal_code=address.postal_code,
        )
        multiplier = 1 + CUSTOM_DESIGN_SURCHARGE / Decimal("100")
        total = Decimal("0")
        customized_items = []
        for item in items:
            product = Product.objects.select_for_update().get(pk=item["product"].pk)
            if not product.is_active:
                raise OrderError(f"Product '{product.name}' is not available.")
            is_custom = product.pk in design_product_ids
            unit_price = (
                (product.price * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                if is_custom
                else product.price
            )
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit_price=unit_price,
                quantity=item["quantity"],
                surcharge_percent=CUSTOM_DESIGN_SURCHARGE if is_custom else Decimal("0"),
            )
            if is_custom:
                customized_items.append(order_item)
            total += order_item.total_price
        order.total_price = total
        order.save(update_fields=["total_price"])

        if design:
            custom_design = CustomDesign.objects.create(
                order=order,
                description=design["description"],
                surcharge_percent=CUSTOM_DESIGN_SURCHARGE,
            )
            custom_design.order_items.set(customized_items)
            for position, (data, extension) in enumerate(design["images"]):
                CustomDesignImage.objects.create(
                    design=custom_design,
                    position=position,
                    # upload_to (design_image_path) turns this into a random
                    # designs/YYYY/MM/<uuid><ext> path on the storage.
                    image=ContentFile(data, name=f"design{extension}"),
                )
    return order
