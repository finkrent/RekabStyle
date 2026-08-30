from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from orders.models import Order
from payments.models import Payment
from payments.services.payments import PaymentError, initiate_payment, verify_and_complete_payment
from payments.services.zibal import ZibalError, payment_url


class InitiatePaymentView(APIView):
    """POST /api/v1/payments/initiate/ {"order_id": <id>} -> {payment_url, track_id}

    Requests a Zibal payment session for one of the user's pending orders.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")
        if not order_id:
            return Response(
                {"detail": "order_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        order = get_object_or_404(Order, pk=order_id, user=request.user)

        callback_url = settings.ZIBAL["CALLBACK_URL"] or request.build_absolute_uri(
            reverse("payment-callback")
        )
        try:
            payment = initiate_payment(order, callback_url)
        except PaymentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ZibalError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
            )

        return Response(
            {
                "detail": "Payment initiated. Redirect the customer to payment_url.",
                "track_id": payment.authority,
                "payment_url": payment_url(payment.authority),
                "amount": payment.amount,
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentCallbackView(APIView):
    """GET /api/v1/payments/callback/ - Zibal redirects the customer's browser here.

    The payment is verified server-side; the callback's own success flag is
    never trusted on its own.
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

        if request.query_params.get("success") != "1":
            return self._respond(request, order=None, paid=False, detail="Payment was cancelled or failed.")

        try:
            payment = verify_and_complete_payment(track_id)
        except PaymentError as exc:
            return self._respond(request, order=None, paid=False, detail=str(exc))
        except ZibalError as exc:
            return self._respond(request, order=None, paid=False, detail=str(exc))

        return self._respond(
            request, order=payment.order, paid=True, detail="Payment verified successfully."
        )

    def _respond(self, request, order, paid, detail):
        """Redirect to the frontend result page when configured, else return JSON."""
        frontend_url = settings.FRONTEND_PAYMENT_RESULT_URL
        if frontend_url:
            query = {"status": "paid" if paid else "failed", "detail": detail}
            if order:
                query["order_number"] = order.order_number
            return HttpResponseRedirect(f"{frontend_url}?{urlencode(query)}")

        payload = {"detail": detail, "status": "paid" if paid else "failed"}
        if order:
            payload["order_number"] = order.order_number
        return Response(payload)


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
                "detail": "Payment verified successfully.",
                "order_number": payment.order.order_number,
                "order_status": payment.order.status,
                "payment_status": payment.status,
            }
        )
