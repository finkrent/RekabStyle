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
        fields = ["id", "product", "product_name", "unit_price", "quantity", "total_price"]


class CustomDesignImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomDesignImage
        fields = ["position", "image"]


class CustomDesignSerializer(serializers.ModelSerializer):
    images = CustomDesignImageSerializer(many=True, read_only=True)

    class Meta:
        model = CustomDesign
        fields = ["description", "surcharge_percent", "images", "created_at"]


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
    items = OrderItemInputSerializer(many=True)
    # Optional: defaults to the user's most recently added address.
    address_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("An order must contain at least one item.")
        return value


class CustomDesignOrderCreateSerializer(serializers.Serializer):
    """Multipart input for POST /api/v1/orders/custom-design/.

    `items` is sent as a JSON string (multipart forms have no list type):
    '[{"product_id": 1, "quantity": 2}]'. It is decoded and validated with
    OrderItemInputSerializer in validate_items. `images` accepts between one
    and CUSTOM_DESIGN["MAX_IMAGES"] image files.
    """

    items = serializers.CharField()
    description = serializers.CharField(
        max_length=settings.CUSTOM_DESIGN["DESCRIPTION_MAX_LENGTH"],
        trim_whitespace=True,
    )
    images = serializers.ListField(
        child=serializers.FileField(),
        min_length=1,
        max_length=settings.CUSTOM_DESIGN["MAX_IMAGES"],
    )
    # Optional: defaults to the user's most recently added address.
    address_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_items(self, value):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise serializers.ValidationError(
                "items must be a JSON array of {product_id, quantity} objects."
            )
        if not isinstance(decoded, list) or not decoded:
            raise serializers.ValidationError(
                "items must be a non-empty JSON array of {product_id, quantity} objects."
            )
        inner = OrderItemInputSerializer(data=decoded, many=True)
        inner.is_valid(raise_exception=True)
        return inner.validated_data
