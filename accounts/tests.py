from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Address, OtpCode
from accounts.services.otp import request_otp
from notifications.services.sms import SmsError, send_otp_sms

User = get_user_model()

REQUEST_OTP_URL = reverse("request-otp")
VERIFY_OTP_URL = reverse("verify-otp")
COMPLETE_REGISTRATION_URL = reverse("complete-registration")
PROFILE_URL = reverse("profile")
ADDRESS_LIST_URL = reverse("address-list")
REFRESH_URL = reverse("token-refresh")
LOGOUT_URL = reverse("logout")

VALID_NATIONAL_ID_1 = "0012345679"
VALID_NATIONAL_ID_2 = "0012345687"
INVALID_NATIONAL_ID = "0012345678"

SMS_TARGET = "notifications.services.sms.send_otp_sms"
SEND_SMS_TARGET = "notifications.services.sms.send_sms"
PHONE = "09123456789"


class RequestOtpTests(TestCase):
    @patch(SMS_TARGET)
    def test_request_otp_success(self, mock_send):
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OtpCode.objects.count(), 1)
        self.assertEqual(mock_send.call_args[0][0], PHONE)

    def test_request_otp_invalid_phone(self):
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": "12345"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OtpCode.objects.count(), 0)

    @patch(SMS_TARGET)
    def test_request_otp_normalizes_phone_number(self, mock_send):
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": "+989123456789"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OtpCode.objects.first().phone_number, PHONE)

    @patch(SMS_TARGET)
    def test_request_otp_cooldown(self, mock_send):
        self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry_after", response.data)
        self.assertEqual(OtpCode.objects.count(), 1)

    def test_request_otp_hourly_rate_limit(self):
        for _ in range(settings.OTP["MAX_REQUESTS_PER_HOUR"]):
            otp, _code = request_otp(PHONE)
            OtpCode.objects.filter(pk=otp.pk).update(
                created_at=timezone.now() - timedelta(minutes=10)
            )
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 429)

    @patch(SMS_TARGET)
    def test_otp_not_stored_in_plain_text(self, mock_send):
        self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        code = mock_send.call_args[0][1]
        otp = OtpCode.objects.first()
        self.assertNotEqual(otp.code_hash, code)
        self.assertNotIn(code, otp.code_hash)

    @patch(SMS_TARGET, side_effect=SmsError("gateway down"))
    def test_sms_failure_removes_otp(self, mock_send):
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(OtpCode.objects.count(), 0)


class OtpSmsMessageTests(TestCase):
    @patch(SEND_SMS_TARGET)
    def test_otp_message_is_multi_line_and_contains_code(self, mock_send_sms):
        send_otp_sms(PHONE, "123456")
        message = mock_send_sms.call_args[0][1]
        self.assertIn("123456", message)
        self.assertIn("\n", message)  # multi-line message
        self.assertNotIn("\\n", message)  # literal sequences were converted


class VerifyOtpTests(TestCase):
    def _request_otp(self, phone=PHONE):
        with patch(SMS_TARGET) as mock_send:
            self.client.post(REQUEST_OTP_URL, {"phone_number": phone})
        return mock_send.call_args[0][1]

    def test_verify_existing_user_logs_in(self):
        existing = User.objects.create_user(phone_number=PHONE)
        code = self._request_otp()
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["logged_in"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing.pk)

    def test_verify_new_phone_stages_signup_without_creating_user(self):
        code = self._request_otp()
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["national_id_required"])
        # The user must not exist in the database before the national ID step.
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(self.client.session["pending_signup_phone"], PHONE)

    def test_used_otp_rejected(self):
        User.objects.create_user(phone_number=PHONE)
        code = self._request_otp()
        self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        self.client.logout()
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        self.assertEqual(response.status_code, 400)

    def test_invalid_otp_rejected(self):
        self._request_otp()
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": "000000"})
        self.assertEqual(response.status_code, 400)

    def test_expired_otp_rejected(self):
        self._request_otp()
        OtpCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": "123456"})
        self.assertEqual(response.status_code, 400)

    def test_too_many_attempts_locks_otp(self):
        self._request_otp()
        for _ in range(settings.OTP["MAX_VERIFY_ATTEMPTS"]):
            self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": "000000"})
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": "000000"})
        self.assertEqual(response.status_code, 429)


class CompleteRegistrationTests(TestCase):
    def _stage_signup(self, phone=PHONE):
        """Verify an OTP for a not-yet-registered phone (sets the pending session)."""
        with patch(SMS_TARGET) as mock_send:
            self.client.post(REQUEST_OTP_URL, {"phone_number": phone})
        code = mock_send.call_args[0][1]
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": phone, "otp": code})
        self.assertTrue(response.data["national_id_required"])

    def test_requires_staged_signup(self):
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": VALID_NATIONAL_ID_1}
        )
        self.assertEqual(response.status_code, 403)

    def test_complete_registration_creates_user_and_logs_in(self):
        self._stage_signup()
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": VALID_NATIONAL_ID_1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["logged_in"])
        user = User.objects.get(phone_number=PHONE)
        self.assertEqual(user.national_id, VALID_NATIONAL_ID_1)
        self.assertNotIn("pending_signup_phone", self.client.session)

    def test_invalid_national_id_rejected(self):
        self._stage_signup()
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": INVALID_NATIONAL_ID}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_national_id_rejected_and_user_not_created(self):
        User.objects.create_user(
            phone_number="09120000001", national_id=VALID_NATIONAL_ID_1
        )
        self._stage_signup()
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": VALID_NATIONAL_ID_1}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("already exists", response.data["detail"])
        # Only the pre-existing account; no user was created.
        self.assertEqual(User.objects.count(), 1)

    def test_phone_race_rejected(self):
        self._stage_signup()
        User.objects.create_user(phone_number=PHONE)
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": VALID_NATIONAL_ID_1}
        )
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("pending_signup_phone", self.client.session)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone_number=PHONE, national_id=VALID_NATIONAL_ID_1
        )
        self.client.force_login(self.user)

    def test_get_profile(self):
        response = self.client.get(PROFILE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone_number"], PHONE)
        self.assertEqual(response.data["addresses"], [])

    def test_update_profile(self):
        response = self.client.patch(
            PROFILE_URL,
            {"first_name": "Ali", "last_name": "Rezaei"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ali")

    def test_identity_fields_are_read_only(self):
        response = self.client.patch(
            PROFILE_URL,
            {"phone_number": "09999999999", "national_id": VALID_NATIONAL_ID_2},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, PHONE)
        self.assertEqual(self.user.national_id, VALID_NATIONAL_ID_1)

    def test_get_profile_returns_profile_complete(self):
        response = self.client.get(PROFILE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["profile_complete"])

        Address.objects.create(
            user=self.user, address="Tehran, Vanak St. 1", postal_code=1234567890
        )
        self.user.first_name = "Ali"
        self.user.last_name = "Rezaei"
        self.user.save()

        response = self.client.get(PROFILE_URL)
        self.assertTrue(response.data["profile_complete"])

    def test_profile_complete_is_read_only(self):
        response = self.client.patch(
            PROFILE_URL,
            {
                "first_name": "Ali",
                "last_name": "Rezaei",
                "profile_complete": True,
            },
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["profile_complete"])

class AddressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone_number=PHONE)
        self.other = User.objects.create_user(phone_number="09120000001")
        self.client.force_login(self.user)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            ADDRESS_LIST_URL, {"address": "Tehran", "postal_code": "1234567890"}
        )
        self.assertEqual(response.status_code, 401)

    def test_create_and_list_own_addresses(self):
        response = self.client.post(
            ADDRESS_LIST_URL, {"address": "Tehran, Vanak", "postal_code": "1234567890"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Address.objects.count(), 1)

        Address.objects.create(
            user=self.other, address="Karaj", postal_code="0987654321"
        )
        response = self.client.get(ADDRESS_LIST_URL)
        self.assertEqual(response.data["count"], 1)  # only own addresses

    def test_invalid_postal_code_rejected(self):
        response = self.client.post(
            ADDRESS_LIST_URL, {"address": "Tehran", "postal_code": "12345"}
        )
        self.assertEqual(response.status_code, 400)

    def test_update_and_delete_address(self):
        address = Address.objects.create(
            user=self.user, address="Tehran", postal_code="1234567890"
        )
        detail_url = reverse("address-detail", args=[address.pk])
        response = self.client.patch(
            detail_url, {"address": "Tehran, Niavaran"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        address.refresh_from_db()
        self.assertEqual(address.address, "Tehran, Niavaran")

        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Address.objects.count(), 0)

    def test_cannot_access_another_users_address(self):
        address = Address.objects.create(
            user=self.other, address="Karaj", postal_code="0987654321"
        )
        response = self.client.get(reverse("address-detail", args=[address.pk]))
        self.assertEqual(response.status_code, 404)

class JwtAuthTests(TestCase):
    REFRESH_COOKIE = settings.JWT_REFRESH_COOKIE["NAME"]

    def _login(self):
        """Sign in an existing user through the OTP flow and return the response."""
        User.objects.create_user(phone_number=PHONE)
        with patch(SMS_TARGET) as mock_send:
            self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        code = mock_send.call_args[0][1]
        response = self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        self.assertEqual(response.status_code, 200)
        return response

    def _set_refresh_cookie(self, value):
        self.client.cookies[self.REFRESH_COOKIE] = value

    def _cookie(self, response):
        return response.cookies[self.REFRESH_COOKIE]

    def test_verify_otp_returns_access_and_sets_refresh_cookie(self):
        response = self._login()
        self.assertIn("access", response.data)
        self.assertNotIn("refresh", response.data)  # never exposed to JavaScript
        cookie = self._cookie(response)
        self.assertTrue(cookie.value)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/v1/accounts/")

    def test_access_token_grants_api_access(self):
        access = self._login().data["access"]
        response = self.client.get(PROFILE_URL, HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone_number"], PHONE)

    def test_complete_registration_sets_refresh_cookie(self):
        with patch(SMS_TARGET) as mock_send:
            self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        code = mock_send.call_args[0][1]
        self.client.post(VERIFY_OTP_URL, {"phone_number": PHONE, "otp": code})
        response = self.client.post(
            COMPLETE_REGISTRATION_URL, {"national_id": VALID_NATIONAL_ID_1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertTrue(self._cookie(response).value)
        profile = self.client.get(
            PROFILE_URL, HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["national_id"], VALID_NATIONAL_ID_1)

    def test_refresh_endpoint_works_with_cookie_only(self):
        self._login()
        response = self.client.post(REFRESH_URL, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        rotated = self._cookie(response).value  # rotation sets a new cookie
        self.assertTrue(rotated)
        self._set_refresh_cookie(rotated)
        second = self.client.post(REFRESH_URL, {})
        self.assertEqual(second.status_code, 200)
        self.assertIn("access", second.data)

    def test_old_refresh_token_blacklisted_after_rotation(self):
        self._login()
        old_cookie = self.client.cookies[self.REFRESH_COOKIE].value
        response = self.client.post(REFRESH_URL, {})  # rotation blacklists the old token
        self.assertEqual(response.status_code, 200)
        self._set_refresh_cookie(old_cookie)
        replay = self.client.post(REFRESH_URL, {})
        self.assertEqual(replay.status_code, 401)

    def test_refresh_with_invalid_cookie_returns_401_and_clears_cookie(self):
        self._set_refresh_cookie("not-a-token")
        response = self.client.post(REFRESH_URL, {})
        self.assertEqual(response.status_code, 401)
        cookie = self._cookie(response)
        self.assertEqual(cookie.value, "")
        self.assertEqual(cookie["max-age"], 0)

    def test_logout_blacklists_refresh_token_and_clears_cookie(self):
        access = self._login().data["access"]
        response = self.client.post(LOGOUT_URL, HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, 200)
        cookie = self._cookie(response)
        self.assertEqual(cookie.value, "")
        self.assertEqual(cookie["max-age"], 0)
        replay = self.client.post(REFRESH_URL, {})
        self.assertEqual(replay.status_code, 401)

    def test_invalid_bearer_token_rejected(self):
        response = self.client.get(PROFILE_URL, HTTP_AUTHORIZATION="Bearer bogus")
        self.assertEqual(response.status_code, 401)

    def test_missing_credentials_rejected(self):
        response = self.client.get(PROFILE_URL)
        self.assertIn(response.status_code, (401, 403))


class DebugOtpTests(TestCase):
    """The DEBUG=True + OTP_DEBUG_RETURN_CODE helper used for manual testing."""

    @override_settings(DEBUG=True, OTP_DEBUG_RETURN_CODE=True)
    def test_debug_mode_returns_code_without_sms(self):
        response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 200)
        self.assertIn("debug_code", response.data)
        self.assertEqual(OtpCode.objects.count(), 1)

    @override_settings(DEBUG=True, OTP_DEBUG_RETURN_CODE=False)
    def test_debug_mode_disabled_without_flag(self):
        with patch(SMS_TARGET) as mock_send:
            response = self.client.post(REQUEST_OTP_URL, {"phone_number": PHONE})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("debug_code", response.data)
        mock_send.assert_called_once()
