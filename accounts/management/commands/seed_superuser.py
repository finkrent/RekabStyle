"""Idempotent superuser seed for local development."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

SEED_PHONE_NUMBER = "09123456789"
SEED_PASSWORD = "12345678"


class Command(BaseCommand):
    help = (
        "Seed one superuser with phone number 09123456789 and password "
        "12345678. Idempotent: re-running skips when the seed superuser "
        "already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow seeding even when DEBUG is False (production).",
        )

    def handle(self, *args, **options):
        self._refuse_outside_debug_unless_forced(options["force"])

        existing = User.objects.filter(phone_number=SEED_PHONE_NUMBER).first()
        if existing is not None:
            self._report_existing(existing)
            return

        User.objects.create_superuser(SEED_PHONE_NUMBER, password=SEED_PASSWORD)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded superuser: phone={SEED_PHONE_NUMBER} password={SEED_PASSWORD}"
            )
        )

    def _report_existing(self, user):
        if user.is_superuser:
            self.stdout.write(
                self.style.WARNING(
                    f"Seed superuser already exists ({user.phone_number}); skipping."
                )
            )
            return
        raise CommandError(
            f"Phone number {user.phone_number} already belongs to a "
            "non-superuser; refusing to overwrite it."
        )

    @staticmethod
    def _refuse_outside_debug_unless_forced(force):
        if settings.DEBUG or force:
            return
        raise CommandError(
            "Refusing to seed a superuser while DEBUG=False: a known default "
            "password is unsafe in production. Pass --force to override."
        )
