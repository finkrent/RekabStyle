"""Kavenegar REST API integration.

This is the ONLY module in the project that communicates with Kavenegar.
Implements the official REST API (https://kavenegar.com/rest.html) directly
with `requests` - no SDK is used.

Endpoint used:
  - POST /v1/{API-KEY}/verify/lookup.json

lookup can only send templates that were created and approved in the
Kavenegar panel: the Persian message texts live there (the template names
are configured in settings.KAVENEGAR_TEMPLATES) and this module passes
tokens that the panel template substitutes via %token / %token2 / %token3.
A response is successful when `return.status` is 200.
"""
import logging
import re
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kavenegar.com/v1"
LOOKUP_PATH = "verify/lookup.json"
TIMEOUT_SECONDS = 10

# lookup tokens accept only latin letters and digits (they are substituted
# into fixed panel-approved text); everything else is stripped.
_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")


class SmsError(Exception):
    """Raised when an SMS could not be sent. Message is user-facing."""


def _token(value):
    """Sanitize a lookup token: latin letters and digits only.

    Order numbers such as 20260915-1A2B3C4D are sent as 202609151A2B3C4D.
    Decimal amounts are sent as whole numbers (money is stored in whole
    Toman) so no decimal point survives the sanitization.
    """
    if isinstance(value, Decimal):
        try:
            value = value.quantize(Decimal("1"))
        except InvalidOperation:  # more than 28 significant digits
            value = int(value)
    return _TOKEN_RE.sub("", str(value))


def _post(path, params):
    api_key = settings.KAVENEGAR_API_KEY
    if not api_key:
        raise SmsError("SMS service is not configured.")

    url = f"{BASE_URL}/{api_key}/{path}"
    try:
        response = requests.post(url, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("Kavenegar request to %s failed: %s", path, exc)
        raise SmsError("SMS provider is currently unreachable.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("Kavenegar returned invalid JSON from %s: %s", path, response.text[:200])
        raise SmsError("Invalid response from SMS provider.") from exc

    status = payload.get("return", {}).get("status")
    if status != 200:
        logger.error("Kavenegar rejected request to %s: %s", path, payload.get("return"))
        raise SmsError("SMS provider rejected the request.")
    return payload.get("entries")


def verify_lookup(phone_number, template, token, token2=None, token3=None):
    """Send a pre-approved Kavenegar template via verify/lookup.json.

    `template` must exist and be approved in the Kavenegar panel; the
    tokens are substituted into it via %token/%token2/%token3 and may
    contain only latin letters and digits (sanitized here). Raises
    SmsError on any failure.
    """
    params = {
        "receptor": phone_number,
        "template": template,
        "token": _token(token),
    }
    if token2 is not None:
        params["token2"] = _token(token2)
    if token3 is not None:
        params["token3"] = _token(token3)
    return _post(LOOKUP_PATH, params)


def send_otp_sms(phone_number, code):
    """Send the OTP through the configured OTP lookup template.

    Panel template placeholders: %token = the OTP code, %token2 = the
    expiry in minutes (derived from settings.OTP["EXPIRE_SECONDS"]).
    """
    expire_minutes = max(1, settings.OTP["EXPIRE_SECONDS"] // 60)
    return verify_lookup(
        phone_number,
        template=settings.KAVENEGAR_TEMPLATES["OTP"],
        token=code,
        token2=expire_minutes,
    )


def send_order_paid_sms_to_customer(phone_number, order_number, total_price):
    """Notify the buyer that their order was paid successfully.

    Panel template placeholders: %token = order number, %token2 = total in
    Toman.
    """
    return verify_lookup(
        phone_number,
        template=settings.KAVENEGAR_TEMPLATES["ORDER_PAID_CUSTOMER"],
        token=order_number,
        token2=total_price,
    )


def _send_order_paid_sms_to_admin(template_key, order_number, customer_phone, total_price):
    admin_phone = settings.ADMIN_PHONE_NUMBER
    if not admin_phone:
        logger.warning("ADMIN_PHONE_NUMBER is not configured; skipping admin SMS.")
        return None
    return verify_lookup(
        admin_phone,
        template=settings.KAVENEGAR_TEMPLATES[template_key],
        token=order_number,
        token2=total_price,
    )


def send_order_paid_sms_to_admin(order_number, customer_phone, total_price):
    """Notify the site administrator about a new successful payment.

    Panel template placeholders: %token = order number, %token2 = total in
    Toman.
    """
    return _send_order_paid_sms_to_admin(
        "ORDER_PAID_ADMIN", order_number, customer_phone, total_price
    )


def send_custom_order_paid_sms_to_admin(order_number, customer_phone, total_price):
    """Notify the site administrator about a new paid custom-design order.

    Panel template placeholders: %token = order number, %token2 = total in
    Toman.
    """
    return _send_order_paid_sms_to_admin(
        "CUSTOM_ORDER_PAID_ADMIN", order_number, customer_phone, total_price
    )
