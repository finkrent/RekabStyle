from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .validators import normalize_phone_number, validate_national_id

phone_validator = RegexValidator(
    regex=r"^09\d{9}$",
    message="Phone number must be a valid Iranian mobile number (09XXXXXXXXX).",
)

postal_code_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Postal code must be exactly 10 digits.",
)


class UserManager(BaseUserManager):
    """Manager for the phone-number based User model."""

    use_in_migrations = True

    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError("A phone number is required.")
        user = self.model(
            phone_number=normalize_phone_number(phone_number),
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(phone_number, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Shop user identified by phone number instead of username.

    Everyone signs in/up with phone number + OTP. A user row is only created
    after the OTP is verified AND a unique national ID is provided.
    Profile details (first/last name) and addresses are completed later but
    are required before checkout. Users may store multiple addresses.
    """

    phone_number = models.CharField(
        "Phone number", max_length=11, unique=True, validators=[phone_validator]
    )
    national_id = models.CharField(
        "National ID",
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_national_id],
    )
    first_name = models.CharField("First name", max_length=100, blank=True)
    last_name = models.CharField("Last name", max_length=100, blank=True)
    is_active = models.BooleanField("Active", default=True)
    is_staff = models.BooleanField("Staff status", default=False)
    date_joined = models.DateTimeField("Date joined", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ("-date_joined",)

    def __str__(self):
        return self.phone_number

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def profile_is_complete(self):
        """True when every field required before checkout is filled."""
        return bool(
            self.national_id
            and self.first_name.strip()
            and self.last_name.strip()
            and self.addresses.exists()
        )


class Address(models.Model):
    """A customer address. A user can store multiple addresses."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="addresses", verbose_name="User"
    )
    address = models.TextField("Address")
    postal_code = models.CharField(
        "Postal code", max_length=10, validators=[postal_code_validator]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)  # newest first; used as checkout default
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.user.phone_number}: {self.address[:30]}"


class OtpCode(models.Model):
    """One-time password sent to a phone number.

    The code itself is never stored in plain text, only a salted hash.
    Used for both sign-in and sign-up; user creation is completed through the
    national ID step after verification.
    """

    phone_number = models.CharField(max_length=11, db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "OTP code"
        verbose_name_plural = "OTP codes"

    def __str__(self):
        return f"OTP for {self.phone_number} ({'used' if self.is_used else 'active'})"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_valid(self):
        return (
            not self.is_used
            and not self.is_expired
            and self.attempt_count < self.max_attempts
        )

    @property
    def max_attempts(self):
        from django.conf import settings

        return settings.OTP["MAX_VERIFY_ATTEMPTS"]

    def mark_used(self):
        self.is_used = True
        self.save(update_fields=["is_used"])
