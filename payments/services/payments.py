"""Payment orchestration: initiation, server-side verification, order updates, SMS."""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.services import sms
from orders.models import DeliveryMethod, Order
from payments.models import Payment
from payments.services.zibal import RIAL_PER_TOMAN, request_payment, verify_payment

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Raised when a payment cannot be initiated or verified. Message is user-facing."""


def initiate_payment(order, callback_url, delivery_method):
    """Resume or create the order's single active payment session."""
    if not isinstance(delivery_method, DeliveryMethod):
        raise PaymentError("Choose a delivery method.")
    pending_timeout = timedelta(seconds=settings.PAYMENT_PENDING_TIMEOUT_SECONDS)
    stale_cutoff = timezone.now() - pending_timeout
    with transaction.atomic():
        try:
            order = (
                Order.objects.select_for_update()
                .select_related("user")
                .get(pk=order.pk)
            )
        except Order.DoesNotExist as exc:
            raise PaymentError("This order is no longer available.") from exc
        if order.status == Order.STATUS_PAID:
            raise PaymentError("This order has already been paid.")
        if order.status != Order.STATUS_PENDING:
            raise PaymentError(f"Orders in status '{order.status}' cannot be paid.")
        pending_payments = list(
            order.payments.select_for_update()
            .filter(status=Payment.STATUS_PENDING)
            .order_by("created_at")
        )
        for pending_payment in pending_payments:
            if pending_payment.authority:
                pending_payment.resumed = True
                return pending_payment
            if pending_payment.created_at > stale_cutoff:
                raise PaymentError(
                    "A payment session is being created. Please retry shortly."
                )
            pending_payment.status = Payment.STATUS_FAILED
            pending_payment.save(update_fields=["status", "updated_at"])

        try:
            delivery_method = DeliveryMethod.objects.select_for_update().get(
                pk=delivery_method.pk
            )
        except DeliveryMethod.DoesNotExist as exc:
            raise PaymentError("This delivery method is not available.") from exc
        if not delivery_method.is_active:
            raise PaymentError("This delivery method is not available.")

        # Order creation stores only item totals. Once delivery is selected,
        # recalculate from the saved item snapshots and add its fee exactly once.
        item_total = sum(
            (item.total_price for item in order.items.all()), 0
        )
        order.delivery_method = delivery_method
        order.delivery_method_code = delivery_method.code
        order.delivery_method_name = delivery_method.name
        order.delivery_fee = delivery_method.price_delta
        order.total_price = item_total + order.delivery_fee
        order.save(
            update_fields=[
                "delivery_method",
                "delivery_method_code",
                "delivery_method_name",
                "delivery_fee",
                "total_price",
                "updated_at",
            ]
        )

        payment = Payment.objects.create(order=order, amount=order.total_price)
    try:
        track_id = request_payment(
            amount=order.total_price,
            callback_url=callback_url,
            order_number=order.order_number,
            mobile=order.user.phone_number,
            national_code=order.user.national_id,
        )
    except Exception:
        payment.status = Payment.STATUS_FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise
    payment.authority = track_id
    payment.save(update_fields=["authority", "updated_at"])
    payment.resumed = False
    order.refresh_from_db()
    return payment


def verify_and_complete_payment(track_id, user=None):
    """Verify a payment with Zibal and, on success, mark it and the order paid.

    - Verification always happens server-side; frontend claims are ignored.
    - The reported amount must match the order amount.
    - Idempotent: an already-successful payment is returned as-is and the
      success SMS is not sent twice.
    """
    payment = Payment.objects.filter(authority=track_id).order_by("-created_at").first()
    if payment is None:
        raise PaymentError("Payment not found.")
    if user is not None and payment.order.user_id != user.id:
        raise PaymentError("Payment not found.")

    if payment.status == Payment.STATUS_SUCCESS:
        return payment

    # Zibal track ids are numeric; anything else can never verify (and would
    # crash the gateway client with a ValueError), so reject it up front.
    if not str(track_id).isdigit():
        raise PaymentError("Payment not found.")

    result = verify_payment(track_id)
    payment.result_code = result["result"]

    if not result["paid"]:
        payment, marked_failed = _mark_payment_failed(payment, result["result"])
        if not marked_failed:
            return payment
        raise PaymentError(result["message"] or "Payment was not completed successfully.")

    if result["amount"] is None or int(result["amount"]) != int(payment.amount) * RIAL_PER_TOMAN:
        payment, marked_failed = _mark_payment_failed(
            payment, result["result"], needs_reconciliation=True
        )
        if not marked_failed:
            return payment
        logger.error(
            "Payment %s amount mismatch: gateway=%s rial expected=%s toman (as %s rial)",
            payment.pk, result["amount"], payment.amount, int(payment.amount) * RIAL_PER_TOMAN,
        )
        return payment

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if payment.status == Payment.STATUS_SUCCESS:
            return payment  # verified concurrently by another request
        another_payment_paid = (
            Payment.objects.filter(
                order_id=order.pk, status=Payment.STATUS_SUCCESS
            ).exists()
        )
        if another_payment_paid or order.status != Order.STATUS_PENDING:
            # The gateway has confirmed money, but the order has already been
            # paid or closed. Never mark an additional attempt as success or
            # send a second order-paid SMS; keep it visible for reconciliation.
            payment.needs_reconciliation = True
            payment.paid_at = timezone.now()
            payment.save(
                update_fields=[
                    "needs_reconciliation",
                    "result_code",
                    "paid_at",
                    "updated_at",
                ]
            )
            logger.error(
                "Payment %s for order %s requires reconciliation: an additional "
                "successful charge was verified for an already paid or closed order.",
                payment.pk,
                order.order_number,
            )
            return payment

        payment.status = Payment.STATUS_SUCCESS
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "result_code", "paid_at", "updated_at"])

        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

    _send_payment_success_sms(payment)
    return payment


def _mark_payment_failed(payment, result_code, needs_reconciliation=False):
    """Mark a failed attempt without overwriting a settled order or payment."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        payment.needs_reconciliation = payment.needs_reconciliation or needs_reconciliation
        if payment.status == Payment.STATUS_SUCCESS or order.status == Order.STATUS_PAID:
            if needs_reconciliation:
                payment.result_code = result_code
                payment.save(
                    update_fields=["result_code", "needs_reconciliation", "updated_at"]
                )
            return payment, False

        payment.status = Payment.STATUS_FAILED
        payment.result_code = result_code
        payment.save(
            update_fields=["status", "result_code", "needs_reconciliation", "updated_at"]
        )
        if order.status == Order.STATUS_PENDING:
            order.status = Order.STATUS_FAILED
            order.save(update_fields=["status", "updated_at"])
    return payment, True


def _send_payment_success_sms(payment):
    """Notify customer and administrator. Never raises."""
    order = payment.order
    customer_phone = order.user.phone_number
    try:
        sms.send_order_paid_sms_to_customer(customer_phone, order.order_number, order.total_price)
    except Exception:
        logger.exception("Customer payment SMS failed for order %s", order.order_number)
    try:
        admin_sms = (
            sms.send_custom_order_paid_sms_to_admin
            if getattr(order, "custom_design", None)
            else sms.send_order_paid_sms_to_admin
        )
        admin_sms(order.order_number, customer_phone, order.total_price)
    except Exception:
        logger.exception("Admin payment SMS failed for order %s", order.order_number)
