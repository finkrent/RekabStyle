"""OTP request/verification logic (rate limiting, cooldown, hashing)."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.models import OtpCode
from accounts.validators import normalize_phone_number


class OtpError(Exception):
    """Raised when an OTP request or verification fails.

    `message` is user-facing, `code` maps to an HTTP status in the API layer
    and `extra` carries additional response fields (e.g. retry_after).
    """

    def __init__(self, message, code="invalid", extra=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


def _hash_code(code):
    """Salted hash so OTP codes are not stored in plain text."""
    salt = secrets.token_hex(8)
    digest = hashlib.sha256((salt + code).encode()).hexdigest()
    return f"{salt}${digest}"


def _check_hash(code, stored):
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    computed = hashlib.sha256((salt + code).encode()).hexdigest()
    return secrets.compare_digest(computed, digest)


def request_otp(phone_number):
    """Generate and store an OTP for the phone number.

    Enforces the cooldown between requests and the hourly request limit.
    Used for both sign-in and sign-up; whether the account exists is decided
    after verification. Returns (otp_instance, plain_code); the caller sends
    the SMS.
    """
    phone_number = normalize_phone_number(phone_number)
    otp_conf = settings.OTP
    now = timezone.now()

    latest = OtpCode.objects.filter(phone_number=phone_number).order_by("-created_at").first()
    if latest and now < latest.created_at + timedelta(seconds=otp_conf["COOLDOWN_SECONDS"]):
        retry_after = int(
            (latest.created_at + timedelta(seconds=otp_conf["COOLDOWN_SECONDS"]) - now).total_seconds()
        ) + 1
        raise OtpError(
            "Please wait before requesting another OTP.",
            code="cooldown",
            extra={"retry_after": retry_after},
        )

    window_start = now - timedelta(hours=1)
    recent_count = OtpCode.objects.filter(
        phone_number=phone_number, created_at__gte=window_start
    ).count()
    if recent_count >= otp_conf["MAX_REQUESTS_PER_HOUR"]:
        raise OtpError(
            "Too many OTP requests. Please try again later.",
            code="rate_limited",
        )

    length = otp_conf["LENGTH"]
    code = "".join(secrets.choice("0123456789") for _ in range(length))
    otp = OtpCode.objects.create(
        phone_number=phone_number,
        code_hash=_hash_code(code),
        expires_at=now + timedelta(seconds=otp_conf["EXPIRE_SECONDS"]),
    )
    return otp, code


def verify_otp(phone_number, code):
    """Verify an OTP. Raises OtpError on any failure; marks the OTP used on success."""
    phone_number = normalize_phone_number(phone_number)
    max_attempts = settings.OTP["MAX_VERIFY_ATTEMPTS"]

    otp = (
        OtpCode.objects.filter(phone_number=phone_number, is_used=False)
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        raise OtpError(
            "No active OTP found for this phone number. Please request a new one.",
            code="not_found",
        )
    if otp.is_expired:
        raise OtpError("This OTP has expired. Please request a new one.", code="expired")
    if otp.attempt_count >= max_attempts:
        raise OtpError(
            "Too many incorrect attempts. Please request a new OTP.",
            code="too_many_attempts",
        )

    otp.attempt_count += 1
    otp.save(update_fields=["attempt_count"])

    if not _check_hash(code, otp.code_hash):
        raise OtpError("Invalid OTP code.", code="invalid")

    otp.mark_used()
    return otp
