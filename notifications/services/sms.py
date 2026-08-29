"""Kavenegar REST API integration.

This is the ONLY module in the project that communicates with Kavenegar.
Implements the official REST API (https://kavenegar.com/rest.html) directly
with `requests` - no SDK is used.

Endpoints used:
  - POST /v1/{API-KEY}/sms/send.json  (plain SMS, including the OTP)
A response is successful when `return.status` is 200.
"""
import logging

import requests
from django.conf import settings
from textwrap import dedent

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kavenegar.com/v1"
TIMEOUT_SECONDS = 10


class SmsError(Exception):
    """Raised when an SMS could not be sent. Message is user-facing."""


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


def send_sms(phone_number, message):
    """Send a plain SMS (supports multi-line messages) via sms/send.json."""
    params = {"receptor": phone_number, "message": message}
    if settings.KAVENEGAR_SENDER:
        params["sender"] = settings.KAVENEGAR_SENDER
    return _post("sms/send.json", params)


def send_otp_sms(phone_number, code):
    """Send the OTP as a plain multi-line SMS.

    Uses sms/send.json (not verify/lookup.json, which requires a Kavenegar
    plan). The message template comes from OTP_SMS_MESSAGE: literal `\\n`
    sequences become real newlines and `{code}` / `{expire_minutes}` are
    substituted.
    """
    expire_minutes = max(1, settings.OTP["EXPIRE_SECONDS"] // 60)
    message = dedent(
        f"""
        فروشگاه رکاب استایل

        کد یکبار مصرف شما: {code}

        این کد تا {expire_minutes} دقیقه معتبر است.
        """
    ).strip()
    return send_sms(phone_number, message)


def send_order_paid_sms_to_customer(phone_number, order_number, total_price):
    """Notify the buyer that their order was paid successfully."""
    message = dedent(
        f"""
        مشتری گرامی،
        سفارش شما با شماره {order_number} با موفقیت پرداخت شد.

        با تشکر از خرید شما.
        فروشگاه رکاب استایل
        """
    ).strip()
    return send_sms(phone_number, message)


def send_order_paid_sms_to_admin(order_number, customer_phone, total_price):
    """Notify the site administrator about a new successful payment."""
    admin_phone = settings.ADMIN_PHONE_NUMBER
    if not admin_phone:
        logger.warning("ADMIN_PHONE_NUMBER is not configured; skipping admin SMS.")
        return None
    message = dedent(
        f"""
        مدیر محترم،
        یک سفارش با شناسه:
        {order_number}
        و قیمت:
        {total_price}
        ثبت شد.

        برای مشاهده جزئیات بیشتر وارد پنل مدیریت شوید.
        """
    ).strip()
    return send_sms(admin_phone, message)
