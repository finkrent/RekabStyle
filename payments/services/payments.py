"""Payment orchestration: initiation, server-side verification, order updates, SMS."""
import logging

from django.db import transaction
from django.utils import timezone

from notifications.services import sms
from orders.models import Order
from payments.models import Payment
from payments.services.zibal import RIAL_PER_TOMAN, request_payment, verify_payment

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Raised when a payment cannot be initiated or verified. Message is user-facing."""


def initiate_payment(order, callback_url):
    """Create a pending Payment and request a payment session from Zibal."""
    if order.status == Order.STATUS_PAID:
        raise PaymentError("This order has already been paid.")
    if order.status != Order.STATUS_PENDING:
        raise PaymentError(f"Orders in status '{order.status}' cannot be paid.")

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

    result = verify_payment(track_id)
    payment.result_code = result["result"]

    if not result["paid"]:
        payment.status = Payment.STATUS_FAILED
        payment.save(update_fields=["status", "result_code", "updated_at"])
        raise PaymentError(result["message"] or "Payment was not completed successfully.")

    if result["amount"] is None or int(result["amount"]) != int(payment.amount) * RIAL_PER_TOMAN:
        payment.status = Payment.STATUS_FAILED
        payment.save(update_fields=["status", "result_code", "updated_at"])
        logger.error(
            "Payment %s amount mismatch: gateway=%s rial expected=%s toman (as %s rial)",
            payment.pk, result["amount"], payment.amount, int(payment.amount) * RIAL_PER_TOMAN,
        )
        raise PaymentError("Payment amount does not match the order amount.")

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.STATUS_SUCCESS:
            return payment  # verified concurrently by another request
        payment.status = Payment.STATUS_SUCCESS
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "result_code", "paid_at", "updated_at"])

        order = payment.order
        if order.status != Order.STATUS_PAID:
            order.status = Order.STATUS_PAID
            order.save(update_fields=["status", "updated_at"])

    _send_payment_success_sms(payment)
    return payment


def _send_payment_success_sms(payment):
    """Notify customer and administrator. Never raises."""
    order = payment.order
    customer_phone = order.user.phone_number
    try:
        sms.send_order_paid_sms_to_customer(customer_phone, order.order_number, order.total_price)
    except Exception:
        logger.exception("Customer payment SMS failed for order %s", order.order_number)
    try:
        sms.send_order_paid_sms_to_admin(order.order_number, customer_phone, order.total_price)
    except Exception:
        logger.exception("Admin payment SMS failed for order %s", order.order_number)
