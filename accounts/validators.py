"""Validation and normalization helpers for Iranian phone numbers and national IDs."""
import re

from django.core.exceptions import ValidationError

IRAN_MOBILE_RE = re.compile(r"^(?:\+98|0098|98|0)?9\d{9}$")


def normalize_phone_number(value):
    """Normalize an Iranian mobile number to the 09XXXXXXXXX format."""
    if value is None:
        return value
    value = re.sub(r"[\s\-().]", "", str(value)).strip()
    if not IRAN_MOBILE_RE.match(value):
        raise ValidationError("Enter a valid Iranian mobile phone number.")
    digits = re.sub(r"^(?:\+98|0098|98|0)", "", value)
    return "0" + digits


def validate_national_id(value):
    """Validate an Iranian national ID (kod-e melli): 10 digits + checksum."""
    value = str(value).strip()
    if not value.isdigit() or len(value) != 10:
        raise ValidationError("National ID must be exactly 10 digits.")
    if len(set(value)) == 1:
        raise ValidationError("Invalid national ID.")
    digits = [int(d) for d in value]
    remainder = sum(d * (10 - i) for i, d in enumerate(digits[:9])) % 11
    check = digits[9]
    expected = remainder if remainder < 2 else 11 - remainder
    if check != expected:
        raise ValidationError("Invalid national ID.")
