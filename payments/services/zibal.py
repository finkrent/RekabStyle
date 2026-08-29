"""Zibal IPG (Internet Payment Gateway) REST integration.

Implemented directly from Zibal's official API documentation / OpenAPI spec:
  https://help.zibal.ir/ipg/
  spec: https://api.zibal.ir/static/helpdocs/ipg.json

Endpoints (JSON over HTTPS to the configured base URL, default gateway.zibal.ir):
  - POST /v1/request     -> register the order; returns a trackId
  - GET  /start/{trackId}-> the hosted payment page the customer is redirected to
  - POST /v1/verify      -> server-side confirmation of the payment

Per the official docs `amount` is expressed in **Rial** while this project's
internal money is in **Toman**, so values are converted (RIAL = TOMAN * 10).

Result codes (from the docs' "جداول" tables):
  - request / verify: 100 = success ("با موفقیت تایید شد")
  - verify:           201 = already verified before (also treated as success)
  - request:          102 = merchant not found, 103 = merchant inactive,
                      104 = merchant invalid, 105 = amount < 1,000 Rial,
                      106 = invalid callbackUrl, 113 = amount above limit,
                      114 = invalid national code, ...
  - verify:           202 = order not paid or failed

Callback (Zibal -> merchant, GET to callbackUrl): query string `success`
(1|0), `trackId`, `orderId` and `status`.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Zibal works in Rial; this project stores money in Toman.
RIAL_PER_TOMAN = 10

REQUEST_PATH = "/v1/request"
START_PATH = "/start/{track_id}"
VERIFY_PATH = "/v1/verify"
TIMEOUT_SECONDS = 15

# Official result codes for the request/verify endpoints.
RESULTS = {
    100: "Successfully verified.",
    102: "Merchant not found.",
    103: "Merchant is inactive / contract not signed.",
    104: "Merchant is invalid.",
    105: "Amount must be greater than 1,000 Rial.",
    106: "Callback URL is invalid (must start with http or https).",
    113: "Amount exceeds the transaction limit.",
    114: "Invalid national code.",
    201: "Already verified before.",
    202: "Order not paid or failed.",
}


class ZibalError(Exception):
    """Raised when the Zibal gateway cannot be used. Message is user-facing."""


def to_rial(amount_toman):
    """Convert an amount in Toman to Rial (per the official Zibal API)."""
    return int(amount_toman) * RIAL_PER_TOMAN


def to_toman(amount_rial):
    """Convert an amount in Rial back to Toman."""
    return int(amount_rial) // RIAL_PER_TOMAN


def _result_message(code):
    return RESULTS.get(code, "Payment gateway returned an unexpected result.")


def _post(path, payload):
    url = settings.ZIBAL["BASE_URL"].rstrip("/") + path
    try:
        response = requests.post(url, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("Zibal request to %s failed: %s", path, exc)
        raise ZibalError("Payment gateway is currently unreachable.") from exc
    try:
        return response.json()
    except ValueError as exc:
        logger.error("Zibal returned invalid JSON from %s: %s", path, response.text[:200])
        raise ZibalError("Invalid response from payment gateway.") from exc


def request_payment(amount, callback_url, order_number, mobile="", national_code=""):
    """Create a payment session and return the Zibal trackId.

    `amount` is in Toman; it is converted to Rial before being sent, per the
    official documentation.
    """
    payload = {
        "merchant": settings.ZIBAL["MERCHANT"],
        "amount": to_rial(amount),
        "callbackUrl": callback_url,
        "description": f"Order {order_number}",
        "orderId": order_number,
    }
    if mobile:
        payload["mobile"] = mobile
    if national_code:
        # Optional; Zibal rejects the transaction if the card owner's national
        # ID does not match this value.
        payload["nationalCode"] = national_code

    data = _post(REQUEST_PATH, payload)
    if data.get("result") != 100 or not data.get("trackId"):
        logger.error("Zibal request failed for order %s: %s", order_number, data)
        raise ZibalError(
            data.get("message") or _result_message(data.get("result"))
        )
    return str(data["trackId"])


def verify_payment(track_id):
    """Verify a payment server-side. Returns a normalized dict.

    `amount` in the returned dict is in Rial (as returned by Zibal).
    """
    data = _post(
        VERIFY_PATH,
        {
            "merchant": settings.ZIBAL["MERCHANT"],
            "trackId": int(track_id),
        },
    )
    result = data.get("result")
    status = data.get("status")
    return {
        "result": result,
        "message": data.get("message", "") or _result_message(result),
        "amount": data.get("amount"),     # Rial
        "paid_at": data.get("paidAt"),
        "status": status,
        "ref_number": data.get("refNumber"),
        "card_number": data.get("cardNumber"),
        "order_id": data.get("orderId"),
        # result 100 = successfully verified; result 201 = already verified
        # before (treated as success so verification stays idempotent).
        "paid": result in (100, 201)
        and status in (1, 2),  # 1 = paid+verified, 2 = paid+unverified
    }


def payment_url(track_id):
    """The gateway page the customer must be redirected to (GET /start/{trackId})."""
    return f"{settings.ZIBAL['BASE_URL'].rstrip('/')}{START_PATH.format(track_id=track_id)}"
