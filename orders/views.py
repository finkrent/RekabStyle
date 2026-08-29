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
from orders.services.orders import OrderError, create_order

User = get_user_model()


class IsOwnerOrStaff(permissions.BasePermission):
    """Only the owning user or a staff member may view an order."""

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj.user_id == request.user.id


class OrderListCreateView(generics.ListCreateAPIView):
    """GET: own orders (all orders for staff) / POST: place an order."""

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
        address = self._resolve_address(request, serializer.validated_data.get("address_id"))
        try:
            order = create_order(request.user, serializer.validated_data["items"], address)
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        output = AdminOrderSerializer if request.user.is_staff else OrderSerializer
        return Response(
            output(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _resolve_address(request, address_id):
        """The requested address, or the user's most recently added one."""
        if address_id:
            return get_object_or_404(Address, pk=address_id, user=request.user)
        return request.user.addresses.first()


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
