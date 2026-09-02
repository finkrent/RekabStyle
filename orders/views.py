from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Address
from orders.models import Order
from orders.serializers import (
    AdminOrderSerializer,
    CustomDesignOrderCreateSerializer,
    OrderCreateSerializer,
    OrderSerializer,
)
from orders.services.design_uploads import ImageValidationError, validate_and_reencode
from orders.services.orders import OrderError, create_custom_design_order, create_order

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
        address = resolve_address(request, serializer.validated_data.get("address_id"))
        try:
            order = create_order(request.user, serializer.validated_data["items"], address)
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        output = AdminOrderSerializer if request.user.is_staff else OrderSerializer
        return Response(
            output(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CustomDesignOrderCreateView(APIView):
    """POST /api/v1/orders/custom-design/ - place a custom-design order.

    multipart/form-data:
    - items: JSON string, e.g. '[{"product_id": 1, "quantity": 2}]'
    - images: 1-3 image files (JPEG/PNG/WEBP, <= 5 MB, <= 6000x6000 px,
      validated by content and re-encoded server-side before storage)
    - description: what should be printed/produced (<= 2000 chars)
    - address_id: optional, defaults to the most recently added address

    Every line item is priced at the product price plus the custom-design
    surcharge (30% by default).
    """

    permission_classes = [permissions.IsAuthenticated]
    # JSONParser intentionally excluded: the design images must arrive as
    # multipart file parts, never as base64 inside JSON bodies.
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        serializer = CustomDesignOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = resolve_address(request, serializer.validated_data.get("address_id"))
        try:
            images = [
                validate_and_reencode(image)
                for image in serializer.validated_data["images"]
            ]
            order = create_custom_design_order(
                request.user,
                serializer.validated_data["items"],
                address,
                serializer.validated_data["description"],
                images,
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
