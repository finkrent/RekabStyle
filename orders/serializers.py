import json

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.models import Address
from orders.models import (
    CustomDesign,
    CustomDesignImage,
    Order,
    OrderItem,
    OrderItemOption,
)
from payments.models import Payment
from products.models import (
    Product,
    ProductAttribute,
    Subcategory,
    resolve_reference_subcategory,
)

# Maximum length accepted for a text attribute's value in an order payload.
OPTION_TEXT_MAX_LENGTH = 200


class PaymentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "amount", "status", "authority", "paid_at", "created_at"]


class OrderItemOptionSerializer(serializers.ModelSerializer):
    """Immutable purchase-time snapshot of one selected product option.

    Identified by the stable `attribute_key`/`choice_key` pair; ids are not
    part of the API.
    """

    class Meta:
        model = OrderItemOption
        fields = [
            "attribute_key",
            "attribute_label",
            "input_type",
            "choice_key",
            "choice_label",
            "text_value",
            "price_delta",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    options = OrderItemOptionSerializer(many=True, read_only=True)

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
            "options",
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

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_payment_status(self, obj):
        # Payments are prefetched; Payment.Meta orders newest first, so the
        # prefetched list starts with the latest payment (no per-order query).
        latest = next(iter(obj.payments.all()), None)
        return latest.status if latest else None

    @extend_schema_field(CustomDesignSerializer(allow_null=True))
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
    """One line of an order payload.

    `subcategory_id` selects the reference subcategory whose attributes
    apply to this item. Optional `selected_options` is a list of
    {"option_key": <attribute key>, "choice_key" | "value": ...} entries;
    attributes and choices are addressed by their stable keys, never ids.
    Attribute validation engages when `subcategory_id` or
    `selected_options` is present; legacy payloads without either keep
    their original behavior.
    """

    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True), source="product"
    )
    quantity = serializers.IntegerField(min_value=1, max_value=99)
    subcategory_id = serializers.PrimaryKeyRelatedField(
        queryset=Subcategory.objects.filter(is_active=True),
        source="subcategory",
        required=False,
        allow_null=True,
    )
    selected_options = serializers.JSONField(required=False, allow_null=True)

    def validate_selected_options(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise serializers.ValidationError(
                    "selected_options must be a JSON array of option objects."
                )
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "selected_options must be a JSON array of option objects."
            )
        return value

    def validate(self, attrs):
        product = attrs.get("product")
        subcategory = attrs.get("subcategory")
        raw_options = attrs.get("selected_options") or []

        if subcategory is not None and not product.subcategories.filter(
            pk=subcategory.pk, is_active=True
        ).exists():
            raise serializers.ValidationError(
                {"subcategory_id": "This product does not belong to the given subcategory."}
            )

        if subcategory is None and not raw_options:
            # Legacy payload: no attributes involved.
            attrs["options"] = []
            return attrs

        if subcategory is None:
            try:
                subcategory = resolve_reference_subcategory(product)
            except ValueError as exc:
                raise serializers.ValidationError({"subcategory_id": str(exc)})
            if subcategory is None:
                raise serializers.ValidationError(
                    {
                        "subcategory_id": (
                            "A reference subcategory is required to submit "
                            "selected_options for this product."
                        )
                    }
                )
            attrs["subcategory"] = subcategory

        # Attributes are addressed by their stable `key` (unique per
        # subcategory); ids never appear in the payload.
        attributes = {
            attribute.key: attribute
            for attribute in subcategory.attributes.filter(is_active=True).prefetch_related(
                "choices"
            )
        }
        if not attributes and raw_options:
            raise serializers.ValidationError(
                {
                    "selected_options": (
                        "The reference subcategory defines no active attributes."
                    )
                }
            )

        choices_by_key = {}
        for attribute in attributes.values():
            for choice in attribute.choices.all():
                choices_by_key[(attribute.pk, choice.key)] = choice

        seen_keys = set()
        options = []
        for raw in raw_options:
            if not isinstance(raw, dict):
                raise serializers.ValidationError(
                    {"selected_options": "Each option must be an object."}
                )
            unknown = set(raw) - {"option_key", "choice_key", "value"}
            if unknown:
                raise serializers.ValidationError(
                    {"selected_options": f"Unexpected option fields: {sorted(unknown)}."}
                )
            option_key = raw.get("option_key")
            if not isinstance(option_key, str) or not option_key.strip():
                raise serializers.ValidationError(
                    {"selected_options": "option_key must be a non-empty string."}
                )
            option_key = option_key.strip()
            if option_key in seen_keys:
                raise serializers.ValidationError(
                    {
                        "selected_options": (
                            f"Duplicate submission for attribute '{option_key}'."
                        )
                    }
                )
            seen_keys.add(option_key)
            attribute = attributes.get(option_key)
            if attribute is None:
                raise serializers.ValidationError(
                    {
                        "selected_options": (
                            f"Attribute '{option_key}' is unknown, inactive, or not "
                            "part of the reference subcategory."
                        )
                    }
                )

            if attribute.input_type == ProductAttribute.INPUT_SELECT:
                if raw.get("value") not in (None, ""):
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Attribute '{attribute.key}' is a select attribute; "
                                "submit a choice_key instead of a text value."
                            )
                        }
                    )
                choice_key = raw.get("choice_key")
                if not isinstance(choice_key, str) or not choice_key.strip():
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Attribute '{attribute.key}' requires a valid choice_key."
                            )
                        }
                    )
                choice = choices_by_key.get((attribute.pk, choice_key.strip()))
                if choice is None:
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Choice '{choice_key.strip()}' is not available for "
                                f"attribute '{attribute.key}'."
                            )
                        }
                    )
                options.append({"attribute": attribute, "choice": choice, "value": ""})
            else:
                if raw.get("choice_key") not in (None, ""):
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Attribute '{attribute.key}' is a text attribute; "
                                "submit a value instead of a choice_key."
                            )
                        }
                    )
                value = raw.get("value")
                if not isinstance(value, str) or not value.strip():
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Attribute '{attribute.key}' requires a non-empty "
                                "text value."
                            )
                        }
                    )
                if len(value.strip()) > OPTION_TEXT_MAX_LENGTH:
                    raise serializers.ValidationError(
                        {
                            "selected_options": (
                                f"Attribute '{attribute.key}' value must be at most "
                                f"{OPTION_TEXT_MAX_LENGTH} characters."
                            )
                        }
                    )
                options.append(
                    {"attribute": attribute, "choice": None, "value": value.strip()}
                )

        selected_keys = {option["attribute"].key for option in options}
        missing = [
            attribute.name
            for attribute in attributes.values()
            if attribute.is_required and attribute.key not in selected_keys
        ]
        if missing:
            raise serializers.ValidationError(
                {"selected_options": f"Required attributes missing: {', '.join(missing)}."}
            )

        attrs["options"] = options
        return attrs


def _parse_items(value):
    """Decode and validate a submitted `items` payload.

    JSON bodies send a real list; multipart bodies send a JSON string.
    Returns the validated [{"product": <Product>, "quantity": int}, ...] list.
    """
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

    While ``settings.CUSTOM_DESIGN["ENABLED"]`` is False the three design
    fields are removed from the contract entirely (see `get_fields`): the
    backend neither validates nor prices them, and stale payloads that
    still send them are accepted as plain orders.
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

    def get_fields(self):
        """Drop the custom-design intake fields while the feature is off.

        Only the declarations are hidden: the field definitions, validators,
        and the service/view logic below stay intact, so restoring the
        checkout flow is a single setting (env CUSTOM_DESIGN_ENABLED=True).
        """
        fields = super().get_fields()
        if not settings.CUSTOM_DESIGN["ENABLED"]:
            for name in (
                "custom_design_product_ids",
                "custom_design_description",
                "images",
            ):
                fields.pop(name, None)
        return fields

    def validate_items(self, value):
        return _parse_items(value)

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


class OrderUpdateSerializer(serializers.Serializer):
    """Replacement item list for PATCH /api/v1/orders/{id}/ (cart-sync).

    The submitted list becomes the order's entire item set: include an
    item to add it or change its quantity, omit it to remove it. Works
    with both `application/json` and multipart bodies (items arrives as
    a JSON string in multipart, same as OrderCreateSerializer).
    """

    items = serializers.JSONField()

    def validate_items(self, value):
        return _parse_items(value)

