"""Order business logic (checkout validation, price snapshot, item edits)."""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from accounts.models import Address
from orders.models import (
    CustomDesign,
    CustomDesignImage,
    Order,
    OrderItem,
    OrderItemOption,
)
from products.models import Product

# The custom-design surcharge applied on top of selected products' prices
# (see settings.CUSTOM_DESIGN). Also stored per order item and per design
# for auditability.
CUSTOM_DESIGN_SURCHARGE = Decimal(str(settings.CUSTOM_DESIGN["SURCHARGE_PERCENT"]))


class OrderError(Exception):
    """Raised when an order cannot be created or updated. Message is user-facing."""


def _lock_product(product):
    """Lock a product row for the transaction and ensure it is still sellable."""
    locked = Product.objects.select_for_update().get(pk=product.pk)
    if not locked.is_active:
        raise OrderError(f"Product '{locked.name}' is not available.")
    return locked


def _create_order_item(order, product, quantity, unit_price, surcharge_percent):
    """Create one line item that snapshots the given price onto the order."""
    return OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        unit_price=unit_price,
        quantity=quantity,
        surcharge_percent=surcharge_percent,
    )


def _options_delta(options):
    """Sum of the selected choices' current price deltas (Toman)."""
    return sum(
        (option["choice"].price_delta for option in options if option["choice"]),
        Decimal("0"),
    )


def _persist_item_options(order_item, options):
    """Snapshot each selected option onto the order item.

    Keys, labels, the text value, and the applied delta are copied at
    purchase time so historical orders stay correct after the current
    attribute/choice definitions are edited or deactivated.
    """
    for option in options:
        attribute = option["attribute"]
        choice = option["choice"]
        OrderItemOption.objects.create(
            item=order_item,
            attribute=attribute,
            attribute_key=attribute.key,
            attribute_label=attribute.name,
            input_type=attribute.input_type,
            choice=choice,
            choice_key=choice.key if choice else "",
            choice_label=choice.label if choice else "",
            text_value=option["value"] or "",
            price_delta=choice.price_delta if choice else Decimal("0"),
        )


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
            product = _lock_product(item["product"])
            options = item.get("options") or []
            # unit price = base price + the sum of the selected choices'
            # current price deltas (frontend-supplied amounts never exist).
            base_price = product.price + _options_delta(options)
            is_custom = product.pk in design_product_ids
            unit_price = (
                (base_price * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                if is_custom
                else base_price
            )
            order_item = _create_order_item(
                order,
                product,
                item["quantity"],
                unit_price,
                CUSTOM_DESIGN_SURCHARGE if is_custom else Decimal("0"),
            )
            _persist_item_options(order_item, options)
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


def update_order_items(order, items):
    """Replace the line items of a pending order (cart-sync PATCH).

    `items` has the same shape as create_order's: a list of
    {"product": <Product>, "quantity": int}. The order's items become
    exactly this list - including a product adds it, omitting one removes
    it - and the total is recomputed with fresh price snapshots (the
    purchase snapshot only freezes at checkout).

    Raises OrderError when the order is not pending, already carries a
    custom design, has no items, or references an unavailable product.
    """
    if order.status != Order.STATUS_PENDING:
        raise OrderError("Only pending orders can be edited.")
    if not items:
        raise OrderError("An order must contain at least one item.")
    # OneToOne reverse access raises RelatedObjectDoesNotExist (an
    # AttributeError subclass), so hasattr is False exactly when no
    # custom design exists.
    if hasattr(order, "custom_design"):
        raise OrderError("Orders with a custom design cannot be edited.")

    with transaction.atomic():
        order.items.all().delete()
        total = Decimal("0")
        for item in items:
            product = _lock_product(item["product"])
            options = item.get("options") or []
            order_item = _create_order_item(
                order,
                product,
                item["quantity"],
                product.price + _options_delta(options),
                Decimal("0"),
            )
            _persist_item_options(order_item, options)
            total += order_item.total_price
        order.total_price = total
        order.save(update_fields=["total_price", "updated_at"])
    return order

