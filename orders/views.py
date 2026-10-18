from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from accounts.models import Address
from orders.models import Order
from orders.serializers import (
    AdminOrderSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    OrderUpdateSerializer,
)
from orders.services.design_uploads import ImageValidationError, validate_and_reencode
from orders.services.orders import OrderError, create_order, update_order_items

User = get_user_model()


class IsOwnerOrStaff(permissions.BasePermission):
    """Only the owning user or a staff member may view an order."""

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj.user_id == request.user.id


def resolve_address(request, address_id):
    """The requested address, or the user's most recently added one."""
    if address_id:
        return get_object_or_404(Address, pk=address_id, user=request.user)
    return request.user.addresses.first()


class OrderListCreateView(generics.ListCreateAPIView):
    """GET: own orders (all orders for staff) / POST: place an order.

    POST accepts `application/json` for plain orders and
    `multipart/form-data`. While settings.CUSTOM_DESIGN["ENABLED"] is False
    the custom-design fields are dropped from the contract and ignored;
    with the feature enabled the design images must arrive as file parts.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Order.objects.prefetch_related(
            "items", "items__options", "payments", "custom_design"
        )
        if self.request.user.is_staff:
            return queryset.select_related("user")
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderCreateSerializer
        return AdminOrderSerializer if self.request.user.is_staff else OrderSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = resolve_address(request, serializer.validated_data.get("address_id"))
        try:
            design = self._design_from(serializer.validated_data)
            order = create_order(
                request.user, serializer.validated_data["items"], address, design=design
            )
        except ImageValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        output = AdminOrderSerializer if request.user.is_staff else OrderSerializer
        return Response(
            output(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _design_from(validated_data):
        """The custom-design payload for the service layer, or None.

        Disabled while ``settings.CUSTOM_DESIGN["ENABLED"]`` is False (the
        serializer then also drops the design fields, so stale frontend
        payloads are silently ignored instead of validated). Otherwise the
        serializer's cross-field validation guarantees that whenever
        `custom_design_product_ids` is set, description and images are
        present too.
        """
        if not settings.CUSTOM_DESIGN["ENABLED"]:
            return None
        product_ids = validated_data.get("custom_design_product_ids")
        if not product_ids:
            return None
        return {
            "product_ids": product_ids,
            "description": validated_data["custom_design_description"],
            "images": [
                validate_and_reencode(image) for image in validated_data["images"]
            ],
        }


class OrderDetailView(generics.RetrieveUpdateAPIView):
    """GET a single order / PATCH its item list (cart-sync).

    Users see only their own orders; staff see all. PATCH replaces the
    order's items with the submitted list: include an item to add it or
    change its quantity, omit it to remove it. Only pending orders without
    a custom design can be edited.
    """

    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        queryset = Order.objects.prefetch_related(
            "items", "items__options", "payments", "custom_design"
        )
        if self.request.user.is_staff:
            return queryset.select_related("user")
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return OrderUpdateSerializer
        return AdminOrderSerializer if self.request.user.is_staff else OrderSerializer

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = self.get_serializer(
            data=request.data, partial=kwargs.get("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        try:
            order = update_order_items(order, serializer.validated_data["items"])
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        output = AdminOrderSerializer if request.user.is_staff else OrderSerializer
        return Response(output(order, context={"request": request}).data)
