from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import IntegrityError, transaction
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from accounts.models import Address, OtpCode, User
from accounts.serializers import (
    AddressSerializer,
    CompleteRegistrationSerializer,
    ProfileSerializer,
    RequestOtpSerializer,
    VerifyOtpSerializer,
)
from accounts.services.otp import OtpError, request_otp, verify_otp
from notifications.services import sms

User = get_user_model()

# Map OTP error codes to HTTP statuses (everything else is a plain 400).
OTP_ERROR_STATUS = {
    "cooldown": status.HTTP_429_TOO_MANY_REQUESTS,
    "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "too_many_attempts": status.HTTP_429_TOO_MANY_REQUESTS,
    "conflict": status.HTTP_409_CONFLICT,
}


def _otp_error_response(exc):
    payload = {"detail": exc.message, "code": exc.code}
    payload.update(exc.extra)
    return Response(payload, status=OTP_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST))


def _set_refresh_cookie(response, raw_token):
    """Deliver the refresh token as an httpOnly cookie (never readable by JS)."""
    conf = settings.JWT_REFRESH_COOKIE
    response.set_cookie(
        conf["NAME"],
        raw_token,
        max_age=conf["MAX_AGE"],
        path=conf["PATH"],
        secure=conf["SECURE"],
        httponly=conf["HTTPONLY"],
        samesite=conf["SAMESITE"],
    )


def _clear_refresh_cookie(response):
    conf = settings.JWT_REFRESH_COOKIE
    response.delete_cookie(conf["NAME"], path=conf["PATH"], samesite=conf["SAMESITE"])


class HasPendingSignup(permissions.BasePermission):
    """Allows only sessions that verified an OTP for a not-yet-registered phone."""

    message = "Verify your phone number with an OTP first."

    def has_permission(self, request, view):
        return bool(request.session.get("pending_signup_phone"))


class RequestOtpView(APIView):
    """POST /api/v1/accounts/request-otp/ - send an OTP to the phone number.

    Used for both sign-in and sign-up: whether the account exists is decided
    after OTP verification.
    """

    # Anonymous endpoint: no authentication and no CSRF requirement.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]

        try:
            otp, code = request_otp(phone_number)
        except OtpError as exc:
            return _otp_error_response(exc)

        if settings.DEBUG and settings.OTP_DEBUG_RETURN_CODE:
            # Development helper: skip the real SMS and return the code in
            # the response so the flow can be tested (e.g. in Postman)
            # without sending/receiving an SMS. Requires DEBUG=True AND the
            # explicit OTP_DEBUG_RETURN_CODE flag - never active in production.
            return Response(
                {
                    "detail": "OTP generated in debug mode (SMS skipped).",
                    "expires_in": settings.OTP["EXPIRE_SECONDS"],
                    "debug_code": code,
                }
            )

        try:
            sms.send_otp_sms(phone_number, code)
        except sms.SmsError:
            otp.delete()  # do not leave the user stuck in the cooldown
            return Response(
                {"detail": "Could not send the OTP SMS. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {"detail": "OTP sent successfully.", "expires_in": settings.OTP["EXPIRE_SECONDS"]}
        )


class VerifyOtpView(APIView):
    """POST /api/v1/accounts/verify-otp/ - verify the OTP.

    - Existing phone number: the user is logged in.
    - New phone number: no user is created yet; the verified phone number is
      staged in the session and the client must submit a national ID through
      /accounts/complete-registration/ to finish sign-up.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]
        code = serializer.validated_data["otp"]

        try:
            verify_otp(phone_number, code)
        except OtpError as exc:
            return _otp_error_response(exc)

        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            request.session["pending_signup_phone"] = phone_number
            return Response(
                {
                    "detail": "Phone number verified. Please provide your national ID to complete registration.",
                    "national_id_required": True,
                }
            )

        if not user.is_active:
            return Response(
                {"detail": "This account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "detail": "Logged in successfully.",
                "logged_in": True,
                "profile_complete": user.profile_is_complete,
                "access": str(refresh.access_token),
            }
        )
        _set_refresh_cookie(response, str(refresh))
        return response


class CompleteRegistrationView(APIView):
    """POST /api/v1/accounts/complete-registration/ - finish sign-up.

    Requires a session that verified an OTP for a not-yet-registered phone
    number. Creates the user only when the national ID is valid and not used
    by another account (uniqueness: pre-check + transactional re-check + the
    database-level unique constraint).
    """

    authentication_classes = []
    permission_classes = [AllowAny, HasPendingSignup]

    def post(self, request):
        serializer = CompleteRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = request.session["pending_signup_phone"]
        national_id = serializer.validated_data["national_id"]

        if User.objects.filter(national_id=national_id).exists():
            return self._conflict(
                "An account with this national ID already exists. Please sign in with your phone number."
            )

        try:
            with transaction.atomic():
                if User.objects.filter(phone_number=phone_number).exists():
                    request.session.pop("pending_signup_phone", None)
                    return self._conflict(
                        "An account with this phone number already exists. Please sign in."
                    )
                if User.objects.filter(national_id=national_id).exists():
                    return self._conflict(
                        "An account with this national ID already exists. Please sign in with your phone number."
                    )
                user = User.objects.create_user(
                    phone_number=phone_number, national_id=national_id
                )
        except IntegrityError as exc:
            return self._conflict(
                "An account with this phone number or national ID already exists."
            )

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.pop("pending_signup_phone", None)
        refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "detail": "Registration completed. You are now logged in.",
                "logged_in": True,
                "profile_complete": user.profile_is_complete,
                "access": str(refresh.access_token),
            }
        )
        _set_refresh_cookie(response, str(refresh))
        return response

    @staticmethod
    def _conflict(message):
        return Response({"detail": message, "code": "conflict"}, status=status.HTTP_409_CONFLICT)


class ProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/accounts/profile/ - view and update profile information."""

    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class AddressListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/accounts/addresses/ - manage the user's addresses."""

    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/accounts/addresses/{id}/ - own addresses only."""

    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)


class TokenRefreshView(BaseTokenRefreshView):
    """POST /api/v1/accounts/token/refresh/ - exchange the refresh-token
    cookie for a new access token.

    The refresh token arrives through the httpOnly cookie set at login (the
    body's "refresh" field is still accepted for API clients such as
    Postman). Refresh tokens rotate: the response sets the rotated token as
    the new cookie and the old one is blacklisted server-side.
    """

    authentication_classes = []

    def post(self, request, *args, **kwargs):
        cookie_name = settings.JWT_REFRESH_COOKIE["NAME"]
        data = dict(request.data) if isinstance(request.data, dict) else {}
        refresh_token = data.get("refresh") or request.COOKIES.get(cookie_name, "")
        if not refresh_token:
            response = Response(
                {"detail": "Refresh token is missing.", "code": "token_not_valid"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response
        serializer = self.get_serializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            response = Response(
                {"detail": str(exc), "code": "token_not_valid"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response

        response = Response({"access": serializer.validated_data["access"]})
        rotated = serializer.validated_data.get("refresh")
        if rotated:
            _set_refresh_cookie(response, str(rotated))
        return response


class LogoutView(APIView):
    """POST /api/v1/accounts/logout/ - blacklist the refresh token and
    clear its cookie. Purely token-based: no CSRF requirement."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE["NAME"])
        if raw_token:
            try:
                RefreshToken(raw_token).blacklist()
            except TokenError:
                pass  # already expired/invalid - nothing left to revoke
        response = Response({"detail": "Logged out successfully."})
        _clear_refresh_cookie(response)
        return response
