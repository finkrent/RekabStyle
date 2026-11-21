from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import OtpCode


class CleanupOtpCodesCommandTests(TestCase):
    def _create_otp(self, *, expires_at):
        return OtpCode.objects.create(
            phone_number="09123456789",
            code_hash="not-a-real-otp-hash",
            expires_at=expires_at,
        )

    def test_deletes_codes_expired_for_more_than_one_day(self):
        now = timezone.now()
        expired_yesterday = self._create_otp(
            expires_at=now - timedelta(days=1, seconds=1)
        )
        expired_recently = self._create_otp(
            expires_at=now - timedelta(hours=12)
        )
        still_valid = self._create_otp(expires_at=now + timedelta(minutes=3))

        call_command("cleanup_otps")

        self.assertFalse(OtpCode.objects.filter(pk=expired_yesterday.pk).exists())
        self.assertTrue(OtpCode.objects.filter(pk=expired_recently.pk).exists())
        self.assertTrue(OtpCode.objects.filter(pk=still_valid.pk).exists())

    def test_cleanup_is_safe_when_there_are_no_old_codes(self):
        self._create_otp(expires_at=timezone.now() - timedelta(hours=12))

        call_command("cleanup_otps")

        self.assertEqual(OtpCode.objects.count(), 1)
