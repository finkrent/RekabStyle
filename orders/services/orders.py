"""Order creation business logic (checkout validation, price snapshot)."""
from decimal import Decimal

from django.db import transaction

from accounts.models import Address
from orders.models import Order, OrderItem
from products.models import Product


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
