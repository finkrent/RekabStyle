import json

from django.conf import settings
from rest_framework import serializers

from accounts.models import Address
from orders.models import CustomDesign, CustomDesignImage, Order, OrderItem
from payments.models import Payment
from products.models import Product


class PaymentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "amount", "status", "authority", "paid_at", "created_at"]


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_name",
            "unit_price",
            "quantity",
            "surcharge_percent",
            "total_price",
        ]


class CustomDesignImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomDesignImage
        fields = ["position", "image"]


class CustomDesignSerializer(serializers.ModelSerializer):
    images = CustomDesignImageSerializer(many=True, read_only=True)
    order_items = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = CustomDesign
        fields = [
            "description",
            "surcharge_percent",
            "status",
            "order_items",
            "images",
            "created_at",
        ]


class OrderSerializer(serializers.ModelSerializer):
    """Customer-facing representation: no sensitive customer data."""

    items = OrderItemSerializer(many=True, read_only=True)
    payment_status = serializers.SerializerMethodField()
    custom_design = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "total_price",
            "payment_status",
            "items",
            "custom_design",
            "shipping_address",
            "shipping_postal_code",
            "created_at",
        ]

    def get_payment_status(self, obj):
        latest = obj.payments.order_by("-created_at").first()
        return latest.status if latest else None

    def get_custom_design(self, obj):
        # getattr returns None for orders without a design (RelatedObjectDoesNotExist
        # subclasses AttributeError); avoids an extra query via try/except.
        design = getattr(obj, "custom_design", None)
        return CustomDesignSerializer(design, context=self.context).data if design else None


class AdminOrderSerializer(OrderSerializer):
    """Staff representation: includes sensitive customer and payment details."""

    customer_phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    customer_national_id = serializers.CharField(source="user.national_id", read_only=True)
    customer_first_name = serializers.CharField(source="user.first_name", read_only=True)
    customer_last_name = serializers.CharField(source="user.last_name", read_only=True)
    payments = PaymentSummarySerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + [
            "customer_phone_number",
            "customer_national_id",
            "customer_first_name",
            "customer_last_name",
            "payments",
        ]


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True), source="product"
    )
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class OrderCreateSerializer(serializers.Serializer):
    """Checkout input for POST /api/v1/orders/.

    Accepts both `application/json` (plain orders, `items` as a real list)
    and `multipart/form-data` (required for the custom-design flow, since
    images must arrive as file parts). In multipart, list-ish fields arrive
    as JSON strings; `items` and `custom_design_product_ids` are therefore
    declared as JSONFields and decoded in their validators so both bodies
    work identically.

    Custom design (the "Custom Design" checkbox on the order page):
    `custom_design_product_ids` selects which of the submitted items get the
    +30% surcharge; `custom_design_description` and 1-3 `images` are then
    required. All-or-nothing: any design field without the full set is a 400.
    """

    items = serializers.JSONField()
    # Optional: defaults to the user's most recently added address.
    address_id = serializers.IntegerField(required=False, allow_null=True)

    # --- Custom design (checkbox on the checkout page) ---
    custom_design_product_ids = serializers.JSONField(required=False, allow_null=True)
    custom_design_description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=settings.CUSTOM_DESIGN["DESCRIPTION_MAX_LENGTH"],
        trim_whitespace=True,
    )
    images = serializers.ListField(
        child=serializers.FileField(),
        min_length=1,
        max_length=settings.CUSTOM_DESIGN["MAX_IMAGES"],
        required=False,
    )

    def validate_items(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise serializers.ValidationError(
                    "items must be a JSON array of {product_id, quantity} objects."
                )
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("An order must contain at least one item.")
        inner = OrderItemInputSerializer(data=value, many=True)
        inner.is_valid(raise_exception=True)
        return inner.validated_data

    def validate_custom_design_product_ids(self, value):
        if value in (None, ""):
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise serializers.ValidationError(
                    "custom_design_product_ids must be a JSON array of product ids."
                )
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError(
                "custom_design_product_ids must be a non-empty JSON array of product ids."
            )
        try:
            ids = [int(raw) for raw in value]
        except (TypeError, ValueError):
            raise serializers.ValidationError("custom_design_product_ids must contain integers.")
        # Deduplicate while preserving order.
        return list(dict.fromkeys(ids))

    def validate(self, attrs):
        product_ids = attrs.get("custom_design_product_ids")
        description = attrs.get("custom_design_description")
        images = attrs.get("images")

        # All-or-nothing: the checkbox flow requires the complete set, and
        # stray design fields without a selection are rejected (no silent
        # no-op design requests).
        if product_ids or description or images:
            if not product_ids:
                raise serializers.ValidationError(
                    {"custom_design_product_ids": "Select at least one item for the custom design."}
                )
            if not description:
                raise serializers.ValidationError(
                    {"custom_design_description": "A design description is required."}
                )
            if not images:
                raise serializers.ValidationError(
                    {"images": "Upload 1-3 design images."}
                )
            item_product_ids = {item["product"].pk for item in attrs["items"]}
            unknown = [pid for pid in product_ids if pid not in item_product_ids]
            if unknown:
                raise serializers.ValidationError(
                    {
                        "custom_design_product_ids": (
                            "Product ids must be part of this order's items: "
                            f"unknown ids {unknown}."
                        )
                    }
                )
        return attrs
