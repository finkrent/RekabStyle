from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import OtpCode


class Command(BaseCommand):
    help = "Delete OTP codes that expired more than 24 hours ago."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        deleted_count, _details = OtpCode.objects.filter(expires_at__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted_count} OTP records expired over 24 hours ago.")
        )
