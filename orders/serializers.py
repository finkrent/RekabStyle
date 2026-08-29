from rest_framework import serializers

from accounts.models import Address
from orders.models import Order, OrderItem
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


class OrderSerializer(serializers.ModelSerializer):
    """Customer-facing representation: no sensitive customer data."""

    items = OrderItemSerializer(many=True, read_only=True)
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "total_price",
            "payment_status",
            "items",
            "shipping_address",
            "shipping_postal_code",
            "created_at",
        ]

    def get_payment_status(self, obj):
        latest = obj.payments.order_by("-created_at").first()
        return latest.status if latest else None


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
