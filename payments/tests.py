from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Address
from orders.models import CustomDesign, Order
from orders.services.orders import create_order
import payments.services.zibal as zibal_module
from payments.models import Payment
from payments.services.zibal import ZibalError
from products.models import Category, Product

User = get_user_model()

INITIATE_URL = reverse("payment-initiate")
VERIFY_URL = reverse("payment-verify")
CALLBACK_URL = reverse("payment-callback")

VALID_NATIONAL_ID = "0012345679"

REQUEST_TARGET = "payments.services.payments.request_payment"
VERIFY_TARGET = "payments.services.payments.verify_payment"
SMS_CUSTOMER_TARGET = "notifications.services.sms.send_order_paid_sms_to_customer"
SMS_ADMIN_TARGET = "notifications.services.sms.send_order_paid_sms_to_admin"
SMS_CUSTOM_ADMIN_TARGET = "notifications.services.sms.send_custom_order_paid_sms_to_admin"


class PaymentTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone_number="09123456789",
            national_id=VALID_NATIONAL_ID,
            first_name="Ali",
            last_name="Rezaei",
        )
        self.address = Address.objects.create(
            user=self.user, address="Tehran, Iran", postal_code="1234567890"
        )
        self.category = Category.objects.create(name="General")
        self.product = Product.objects.create(name="Phone X", price=100000)
        self.product.categories.add(self.category)
        self.order = create_order(
            self.user,
            items=[{"product": self.product, "quantity": 2}],
            address=self.address,
        )

    def _make_payment(self, track_id="TRK123"):
        return Payment.objects.create(
            order=self.order, amount=self.order.total_price, authority=track_id
        )

    @staticmethod
    def _verify_result(paid=True, amount=None, result=100):
        return {
            "result": result,
            "message": "success" if paid else "failed",
            "amount": amount,
            "paid_at": "2026-08-28 12:00:00",
            "paid": paid,
        }


class InitiatePaymentTests(PaymentTestBase):
    @patch(SMS_ADMIN_TARGET)
    @patch(SMS_CUSTOMER_TARGET)
    @patch(REQUEST_TARGET)
    def test_initiate_payment_success(self, mock_request, _m1, _m2):
        mock_request.return_value = "12345"
        self.client.force_login(self.user)
        response = self.client.post(
            INITIATE_URL, {"order_id": self.order.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["track_id"], "12345")
        self.assertIn("/start/12345", response.data["payment_url"])
        payment = Payment.objects.get(authority="12345")
        self.assertEqual(payment.status, Payment.STATUS_PENDING)
        self.assertEqual(payment.amount, self.order.total_price)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args.kwargs["amount"], self.order.total_price)

    def test_initiate_payment_requires_authentication(self):
        response = self.client.post(
            INITIATE_URL, {"order_id": self.order.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)

    def test_cannot_pay_already_paid_order(self):
        self.order.status = Order.STATUS_PAID
        self.order.save()
        self.client.force_login(self.user)
        response = self.client.post(
            INITIATE_URL, {"order_id": self.order.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_pay_another_users_order(self):
        User.objects.create_user(
            phone_number="09120000001",
            national_id="0012345687",
            first_name="Sara",
            last_name="Ahmadi",


        )
        other = User.objects.get(phone_number="09120000001")
        self.client.force_login(other)
        response = self.client.post(
            INITIATE_URL, {"order_id": self.order.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)

    @patch(REQUEST_TARGET, side_effect=ZibalError("gateway down"))
    def test_gateway_failure_marks_payment_failed(self, mock_request):
        self.client.force_login(self.user)
        response = self.client.post(
            INITIATE_URL, {"order_id": self.order.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 502)
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.status, Payment.STATUS_FAILED)


class VerifyPaymentTests(PaymentTestBase):
    @patch(SMS_CUSTOM_ADMIN_TARGET)
    @patch(SMS_ADMIN_TARGET)
    @patch(SMS_CUSTOMER_TARGET)
    @patch(VERIFY_TARGET)
    def test_successful_verification_updates_order(
        self, mock_verify, mock_sms_customer, mock_sms_admin, mock_sms_custom_admin
    ):
        self._make_payment()
        mock_verify.return_value = self._verify_result(amount=int(self.order.total_price) * 10)

        self.client.force_login(self.user)
        response = self.client.post(
            VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["order_status"], Order.STATUS_PAID)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)
        payment = Payment.objects.get(authority="TRK123")
        self.assertEqual(payment.status, Payment.STATUS_SUCCESS)
        self.assertIsNotNone(payment.paid_at)
        mock_sms_customer.assert_called_once()
        mock_sms_admin.assert_called_once()
        mock_sms_custom_admin.assert_not_called()

    @patch(SMS_CUSTOM_ADMIN_TARGET)
    @patch(SMS_ADMIN_TARGET)
    @patch(SMS_CUSTOMER_TARGET)
    @patch(VERIFY_TARGET)
    def test_custom_order_uses_custom_admin_sms(
        self, mock_verify, mock_sms_customer, mock_sms_admin, mock_sms_custom_admin
    ):
        custom_design = CustomDesign.objects.create(
            order=self.order, description="A custom design request"
        )
        custom_design.order_items.add(self.order.items.first())
        self._make_payment()
        mock_verify.return_value = self._verify_result(amount=int(self.order.total_price) * 10)

        self.client.force_login(self.user)
        response = self.client.post(
            VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        mock_sms_customer.assert_called_once()
        mock_sms_custom_admin.assert_called_once()
        mock_sms_admin.assert_not_called()

    @patch(VERIFY_TARGET)
    def test_incorrect_amount_rejected(self, mock_verify):
        self._make_payment()
        mock_verify.return_value = self._verify_result(amount=int(self.order.total_price) * 10 + 5000)
        self.client.force_login(self.user)
        response = self.client.post(
            VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)
        self.assertEqual(Payment.objects.get(authority="TRK123").status, Payment.STATUS_FAILED)

    @patch(VERIFY_TARGET)
    def test_failed_payment_rejected(self, mock_verify):
        self._make_payment()
        mock_verify.return_value = self._verify_result(paid=False, result=103, amount=0)
        self.client.force_login(self.user)
        response = self.client.post(
            VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)

    @patch(SMS_ADMIN_TARGET)
    @patch(SMS_CUSTOMER_TARGET)
    @patch(VERIFY_TARGET)
    def test_duplicate_verification_is_idempotent(self, mock_verify, mock_sms_customer, mock_sms_admin):
        self._make_payment()
        mock_verify.return_value = self._verify_result(amount=int(self.order.total_price) * 10)
        self.client.force_login(self.user)

        first = self.client.post(VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json")
        second = self.client.post(VERIFY_URL, {"track_id": "TRK123"}, content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        # The gateway must only be contacted once and SMS sent once.
        mock_verify.assert_called_once()
        mock_sms_customer.assert_called_once()
        mock_sms_admin.assert_called_once()

    def test_unknown_track_id_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            VERIFY_URL, {"track_id": "NOPE"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    @patch(SMS_ADMIN_TARGET)
    @patch(SMS_CUSTOMER_TARGET)
    @patch(VERIFY_TARGET)
    def test_callback_success_updates_order(self, mock_verify, _m1, _m2):
        self._make_payment()
        mock_verify.return_value = self._verify_result(amount=int(self.order.total_price) * 10)
        response = self.client.get(
            CALLBACK_URL, {"trackId": "TRK123", "success": "1", "status": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)

    @patch(VERIFY_TARGET)
    def test_callback_with_success_zero_does_not_verify(self, mock_verify):
        self._make_payment()
        response = self.client.get(
            CALLBACK_URL, {"trackId": "TRK123", "success": "0", "status": "-1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "failed")
        mock_verify.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)


class ZibalServiceTests(TestCase):
    """Unit tests for payments/services/zibal.py (official Zibal API mapping)."""

    @patch("requests.post")
    def test_request_converts_amount_to_rial_and_sends_national_code(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"trackId": 15966442233311, "result": 100, "message": "success"}
        mock_post.return_value = mock_response

        track_id = zibal_module.request_payment(
            16000,
            "http://yourapiurl.com/callback.php",
            "ORD-1",
            mobile="09123456789",
            national_code="0012345679",
        )
        self.assertEqual(track_id, "15966442233311")
        sent = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent["amount"], 160000)  # 16000 Toman -> 160000 Rial
        self.assertEqual(sent["callbackUrl"], "http://yourapiurl.com/callback.php")
        self.assertEqual(sent["orderId"], "ORD-1")
        self.assertEqual(sent["mobile"], "09123456789")
        self.assertEqual(sent["nationalCode"], "0012345679")

    @patch("requests.post")
    def test_request_rejects_non_100_result(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"result": 102, "message": "merchanty Nope"}
        mock_post.return_value = mock_response
        with self.assertRaises(zibal_module.ZibalError):
            zibal_module.request_payment(16000, "http://callback", "ORD-1")

    @patch("requests.post")
    def test_verify_sends_integer_track_id_and_marks_paid(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {
            "paidAt": "2018-03-25T23:43:01.053000",
            "amount": 160000,
            "result": 100,
            "status": 1,
            "refNumber": 12312,
            "cardNumber": "62741****44",
            "orderId": "2211",
            "message": "success",
        }
        mock_post.return_value = mock_response

        result = zibal_module.verify_payment("15966442233311")
        self.assertIs(result["paid"], True)
        # trackId must be sent as an integer per the API spec.
        self.assertEqual(mock_post.call_args.kwargs["json"]["trackId"], 15966442233311)
        self.assertEqual(result["amount"], 160000)
        self.assertEqual(result["status"], 1)
        self.assertEqual(result["ref_number"], 12312)

    @patch("requests.post")
    def test_verify_201_already_verified_is_treated_as_paid(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"result": 201, "status": 2, "amount": 160000, "message": "previously verified"}
        mock_post.return_value = mock_response
        result = zibal_module.verify_payment("123")
        self.assertIs(result["paid"], True)

    @patch("requests.post")
    def test_verify_202_not_paid_rejected(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"result": 202, "status": 2, "amount": 160000, "message": "not paid"}
        mock_post.return_value = mock_response
        result = zibal_module.verify_payment("123")
        self.assertIs(result["paid"], False)

    def test_currency_conversion(self):
        self.assertEqual(zibal_module.to_rial(200000), 2000000)
        self.assertEqual(zibal_module.to_toman(2000000), 200000)

    def test_payment_url_uses_start_path(self):
        self.assertTrue(zibal_module.payment_url("987654").endswith("/start/987654"))
