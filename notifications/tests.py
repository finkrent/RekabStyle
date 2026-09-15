from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from notifications.services import sms

LOOKUP_TARGET = "notifications.services.sms.requests.post"
LOOKUP_FUNC_TARGET = "notifications.services.sms.verify_lookup"

PHONE = "09123456789"


def _ok_response(entries=None):
    response = Mock()
    response.json.return_value = {
        "return": {"status": 200, "message": "تایید شد"},
        "entries": entries if entries is not None else [],
    }
    return response


class VerifyLookupTests(TestCase):
    """Unit tests for the Kavenegar verify/lookup.json integration."""

    @patch(LOOKUP_TARGET)
    def test_lookup_posts_receptor_template_and_tokens(self, mock_post):
        mock_post.return_value = _ok_response(entries={"messageid": 1})

        entries = sms.verify_lookup(
            PHONE, template="rekab-otp", token="123456", token2="3"
        )

        self.assertEqual(entries, {"messageid": 1})
        self.assertTrue(mock_post.call_args.args[0].endswith("/verify/lookup.json"))
        sent = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent["receptor"], PHONE)
        self.assertEqual(sent["template"], "rekab-otp")
        self.assertEqual(sent["token"], "123456")
        self.assertEqual(sent["token2"], "3")
        self.assertNotIn("token3", sent)  # optional tokens are omitted
        self.assertNotIn("sender", sent)  # lookup has no sender parameter

    @patch(LOOKUP_TARGET)
    def test_lookup_sends_token3_when_given(self, mock_post):
        mock_post.return_value = _ok_response()

        sms.verify_lookup(PHONE, template="t", token="a", token2="b", token3="c")

        sent = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent["token3"], "c")

    @patch(LOOKUP_TARGET)
    def test_tokens_are_sanitized_to_alphanumeric_only(self, mock_post):
        """Kavenegar lookup tokens accept only latin letters and digits."""
        mock_post.return_value = _ok_response()

        sms.verify_lookup(
            PHONE,
            template="rekab-order-paid",
            token="20260915-1A2B3C4D",  # order number with a hyphen
            token2="50000",  # whole Toman amount
        )

        sent = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent["token"], "202609151A2B3C4D")
        self.assertEqual(sent["token2"], "50000")

    @patch(LOOKUP_TARGET)
    def test_decimal_tokens_are_sent_as_whole_numbers(self, mock_post):
        mock_post.return_value = _ok_response()

        sms.verify_lookup(PHONE, template="t", token="x", token2=50000)

        sent = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent["token2"], "50000")

    @patch(LOOKUP_TARGET)
    def test_non_200_status_raises_sms_error(self, mock_post):
        response = Mock()
        response.json.return_value = {
            "return": {"status": 411, "message": "template does not exist"}
        }
        mock_post.return_value = response

        with self.assertRaises(sms.SmsError):
            sms.verify_lookup(PHONE, template="missing", token="1")

    @patch(LOOKUP_TARGET, side_effect=__import__("requests").RequestException("down"))
    def test_unreachable_provider_raises_sms_error(self, mock_post):
        with self.assertRaises(sms.SmsError):
            sms.verify_lookup(PHONE, template="t", token="1")

    @override_settings(KAVENEGAR_API_KEY="")
    def test_missing_api_key_raises_sms_error(self):
        with self.assertRaisesMessage(sms.SmsError, "not configured"):
            sms.verify_lookup(PHONE, template="t", token="1")


class SendHelperTests(TestCase):
    """The public send helpers map onto the configured lookup templates."""

    @patch(LOOKUP_FUNC_TARGET)
    def test_otp_uses_otp_template_with_expiry_minutes(self, mock_lookup):
        sms.send_otp_sms(PHONE, "654321")
        expected_minutes = max(1, settings.OTP["EXPIRE_SECONDS"] // 60)
        mock_lookup.assert_called_once_with(
            PHONE,
            template=settings.KAVENEGAR_TEMPLATES["OTP"],
            token="654321",
            token2=expected_minutes,
        )

    @patch(LOOKUP_FUNC_TARGET)
    def test_customer_order_paid_sms_uses_customer_template(self, mock_lookup):
        sms.send_order_paid_sms_to_customer(PHONE, "20260915-ABC123", 50000)
        mock_lookup.assert_called_once_with(
            PHONE,
            template=settings.KAVENEGAR_TEMPLATES["ORDER_PAID_CUSTOMER"],
            token="20260915-ABC123",  # raw pass-through; verify_lookup sanitizes
            token2=50000,
        )

    @patch(LOOKUP_FUNC_TARGET)
    def test_admin_order_paid_sms_uses_admin_template(self, mock_lookup):
        with override_settings(ADMIN_PHONE_NUMBER="09120000000"):
            sms.send_order_paid_sms_to_admin("20260915-ABC123", PHONE, 50000)
        mock_lookup.assert_called_once_with(
            "09120000000",
            template=settings.KAVENEGAR_TEMPLATES["ORDER_PAID_ADMIN"],
            token="20260915-ABC123",  # raw pass-through; verify_lookup sanitizes
            token2=50000,
        )

    @patch(LOOKUP_FUNC_TARGET)
    def test_custom_admin_order_paid_sms_uses_custom_template(self, mock_lookup):
        with override_settings(ADMIN_PHONE_NUMBER="09120000000"):
            sms.send_custom_order_paid_sms_to_admin("20260915-ABC123", PHONE, 50000)
        mock_lookup.assert_called_once_with(
            "09120000000",
            template=settings.KAVENEGAR_TEMPLATES["CUSTOM_ORDER_PAID_ADMIN"],
            token="20260915-ABC123",  # raw pass-through; verify_lookup sanitizes
            token2=50000,
        )

    @patch(LOOKUP_FUNC_TARGET)
    def test_admin_sms_skipped_without_admin_phone(self, mock_lookup):
        with override_settings(ADMIN_PHONE_NUMBER=""):
            self.assertIsNone(
                sms.send_order_paid_sms_to_admin("20260915-ABC123", PHONE, 50000)
            )
            self.assertIsNone(
                sms.send_custom_order_paid_sms_to_admin("20260915-ABC123", PHONE, 50000)
            )
        mock_lookup.assert_not_called()
