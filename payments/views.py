from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from orders.models import DeliveryMethod, Order
from payments.models import Payment
from payments.services.payments import PaymentError, initiate_payment, verify_and_complete_payment
from payments.services.zibal import ZibalError, payment_url


class InitiatePaymentRequest(serializers.Serializer):
    """Body of POST /api/v1/payments/initiate/."""

    order_id = serializers.IntegerField(help_text="PK of the user's pending order.")
    delivery_method = serializers.SlugRelatedField(
        slug_field="code",
        queryset=DeliveryMethod.objects.filter(is_active=True),
        error_messages={
            "does_not_exist": "This delivery method is not available.",
            "required": "Choose a delivery method.",
        },
    )


class VerifyPaymentRequest(serializers.Serializer):
    """Body of POST /api/v1/payments/verify/."""

    track_id = serializers.CharField(help_text="Authority returned by initiate.")


@extend_schema(
    request=InitiatePaymentRequest,
    responses={
        201: OpenApiResponse(
            description="Created: track_id, payment_url, amount, resumed=false."
        ),
        200: OpenApiResponse(
            description="Recovered session: track_id, payment_url, amount, resumed=true."
        ),
        400: OpenApiResponse(description="order_id missing or order not payable."),
        409: OpenApiResponse(description="An initiation with no gateway response is still in progress."),
        404: OpenApiResponse(description="Order not found for this user."),
        502: OpenApiResponse(description="Payment gateway error."),
    },
)
class InitiatePaymentView(APIView):
    """POST /api/v1/payments/initiate/ {"order_id": <id>} -> {payment_url, track_id}

    Requests a Zibal payment session for one of the user's pending orders.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = InitiatePaymentRequest(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(
            Order, pk=serializer.validated_data["order_id"], user=request.user
        )

        callback_url = settings.ZIBAL["CALLBACK_URL"] or request.build_absolute_uri(
            reverse("payment-callback")
        )
        try:
            payment = initiate_payment(
                order, callback_url, serializer.validated_data["delivery_method"]
            )
        except PaymentError as exc:
            conflict = "being created" in str(exc)
            return Response(
                {"detail": str(exc)},
                status=(
                    status.HTTP_409_CONFLICT if conflict else status.HTTP_400_BAD_REQUEST
                ),
            )
        except ZibalError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
            )

        return Response(
            {
                "detail": (
                    "Payment session recovered. Redirect to payment_url."
                    if getattr(payment, "resumed", False)
                    else "Payment initiated. Redirect the customer to payment_url."
                ),
                "track_id": payment.authority,
                "payment_url": payment_url(payment.authority),
                "amount": payment.amount,
                "resumed": getattr(payment, "resumed", False),
            },
            status=(
                status.HTTP_200_OK
                if getattr(payment, "resumed", False)
                else status.HTTP_201_CREATED
            ),
        )


@extend_schema(
    parameters=[
        OpenApiParameter(
            "trackId", type=str, required=True, description="Zibal authority (track id)."
        ),
        OpenApiParameter(
            "success", type=str, description="'1' when the customer completed payment."
        ),
    ],
    responses={
        200: OpenApiResponse(
            description=(
                "Payment verified. Returns JSON, or a 302 redirect to the frontend "
                "result page when FRONTEND_PAYMENT_RESULT_URL is set."
            )
        ),
        400: OpenApiResponse(description="trackId missing or verification failed."),
    },
)
class PaymentCallbackView(APIView):
    """GET /api/v1/payments/callback/ - Zibal redirects the customer's browser here.

    The payment is verified server-side; the callback's own success flag is
    never trusted on its own. A failed callback is verified too, and a
    confirmed unsuccessful payment marks the order failed.
    """

    # The gateway redirects the customer's browser here; no session/CSRF.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        track_id = request.query_params.get("trackId")
        if not track_id:
            return Response(
                {"detail": "trackId is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            payment = verify_and_complete_payment(track_id)
        except PaymentError as exc:
            payment = (
                Payment.objects.filter(authority=track_id)
                .select_related("order")
                .first()
            )
            return self._respond(
                request,
                order=payment.order if payment else None,
                paid=bool(payment and payment.status == Payment.STATUS_SUCCESS),
                detail=str(exc),
                needs_reconciliation=bool(payment and payment.needs_reconciliation),
            )
        except ZibalError as exc:
            payment = (
                Payment.objects.filter(authority=track_id)
                .select_related("order")
                .first()
            )
            return self._respond(
                request,
                order=payment.order if payment else None,
                paid=bool(payment and payment.status == Payment.STATUS_SUCCESS),
                detail=str(exc),
                needs_reconciliation=bool(payment and payment.needs_reconciliation),
            )

        return self._respond(
            request,
            order=payment.order,
            paid=payment.status == Payment.STATUS_SUCCESS,
            detail=(
                "Payment verified successfully."
                if not payment.needs_reconciliation
                else "Payment requires reconciliation."
            ),
            needs_reconciliation=payment.needs_reconciliation,
        )

    def _respond(self, request, order, paid, detail, needs_reconciliation=False):
        """Redirect to the frontend result page when configured, else return JSON."""
        frontend_url = settings.FRONTEND_PAYMENT_RESULT_URL
        if needs_reconciliation:
            response_status = "reconciliation_required"
        elif paid:
            response_status = "paid"
        else:
            response_status = "failed"
        if frontend_url:
            query = {"status": response_status, "detail": detail}
            if needs_reconciliation:
                query["needs_reconciliation"] = "true"
            if order:
                query["order_number"] = order.order_number
            return HttpResponseRedirect(f"{frontend_url}?{urlencode(query)}")

        payload = {
            "detail": detail,
            "status": response_status,
            "needs_reconciliation": needs_reconciliation,
        }
        if order:
            payload["order_number"] = order.order_number
            payload["order_status"] = order.status
        return Response(payload)


@extend_schema(
    request=VerifyPaymentRequest,
    responses={
        200: OpenApiResponse(
            description="Verified: order_number, order_status, payment_status. Idempotent."
        ),
        400: OpenApiResponse(description="track_id missing or verification failed."),
        502: OpenApiResponse(description="Payment gateway error."),
    },
)
class PaymentVerifyView(APIView):
    """POST /api/v1/payments/verify/ {"track_id": "..."}

    Lets the frontend trigger server-side verification after the customer
    returns from the gateway. Idempotent.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        track_id = request.data.get("track_id")
        if not track_id:
            return Response(
                {"detail": "track_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            payment = verify_and_complete_payment(str(track_id), user=request.user)
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ZibalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "detail": (
                    "Payment requires reconciliation."
                    if payment.needs_reconciliation
                    else "Payment verified successfully."
                ),
                "status": (
                    "reconciliation_required"
                    if payment.needs_reconciliation
                    else payment.status
                ),
                "needs_reconciliation": payment.needs_reconciliation,
                "order_number": payment.order.order_number,
                "order_status": payment.order.status,
                "payment_status": payment.status,
            }
        )
