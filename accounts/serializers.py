from rest_framework import serializers

from accounts.models import Address, User
from accounts.validators import normalize_phone_number, validate_national_id


class RequestOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        return normalize_phone_number(value)


class VerifyOtpSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(min_length=4, max_length=8)

    def validate_phone_number(self, value):
        return normalize_phone_number(value)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP code must contain only digits.")
        return value


class CompleteRegistrationSerializer(serializers.Serializer):
    """Final sign-up step: the required, unique national ID."""

    national_id = serializers.CharField()

    def validate_national_id(self, value):
        value = str(value).strip()
        try:
            validate_national_id(value)
        except serializers.ValidationError:
            raise
        except Exception as exc:
            raise serializers.ValidationError(str(exc))
        return value


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ["id", "address", "postal_code", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    addresses = AddressSerializer(many=True, read_only=True)
    profile_complete = serializers.BooleanField(source="profile_is_complete", read_only=True)

    class Meta:
        model = User
        fields = [
            "phone_number",
            "national_id",
            "first_name",
            "last_name",
            "full_name",
            "addresses",
            "profile_complete",

        ]
        # phone_number and national_id are identity fields, managed by the
        # registration flow / staff, not editable through the profile API.
        # Addresses are managed through the /addresses/ endpoints.
        read_only_fields = ["phone_number", "national_id", "addresses"]

    def get_full_name(self, obj):
        return obj.get_full_name()
