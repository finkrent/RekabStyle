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
)
from orders.services.design_uploads import ImageValidationError, validate_and_reencode
from orders.services.orders import OrderError, create_order

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
    `multipart/form-data` when the "Custom Design" checkbox is used on the
    checkout page (the design images must arrive as file parts).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Order.objects.prefetch_related("items", "payments")
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

        The serializer's cross-field validation guarantees that whenever
        `custom_design_product_ids` is set, description and images are
        present too.
        """
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


class OrderDetailView(generics.RetrieveAPIView):
    """GET a single order. Users see only their own orders; staff see all."""

    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        queryset = Order.objects.prefetch_related("items", "payments")
        if self.request.user.is_staff:
            return queryset.select_related("user")
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        return AdminOrderSerializer if self.request.user.is_staff else OrderSerializer
