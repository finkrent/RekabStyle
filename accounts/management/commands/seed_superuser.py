"""Idempotent superuser seed for local development."""

import random

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.validators import normalize_phone_number

# Common Iranian mobile operator prefixes; a seeded phone number should look
# plausible next to real customer numbers (full form: 09 + prefix tail).
_OPERATOR_PREFIXES = (
    "0910", "0911", "0912", "0913", "0914", "0915", "0916", "0917", "0918",
    "0919", "0920", "0921", "0930", "0933", "0935", "0936", "0937", "0938",
    "0939", "0990", "0991", "0992", "0993", "0994", "0996",
)

DEFAULT_PASSWORD = "123456"
MAX_PHONE_ATTEMPTS = 10


class Command(BaseCommand):
    help = (
        "Seed one superuser with a random phone number and a fixed password "
        "(default 123456). Idempotent: re-running skips when a superuser "
        "already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--phone-number",
            default=None,
            help="Explicit phone number (09XXXXXXXXX) instead of a random one.",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help="Password for the seeded superuser (default: %(default)s).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow seeding even when DEBUG is False (production).",
        )

    def handle(self, *args, **options):
        self._refuse_outside_debug_unless_forced(options["force"])

        existing = User.objects.filter(is_superuser=True).first()
        if existing is not None:
            self.stdout.write(
                self.style.WARNING(
                    f"Superuser already exists ({existing.phone_number}); skipping."
                )
            )
            return

        self._create_superuser(options["password"], options["phone_number"])

    def _refuse_outside_debug_unless_forced(self, force):
        if settings.DEBUG or force:
            return
        raise CommandError(
            "Refusing to seed a superuser while DEBUG=False: a known default "
            "password is unsafe in production. Pass --force to override."
        )

    def _create_superuser(self, password, phone_number):
        if phone_number is None:
            phone_number = self._unique_random_phone_number()
        else:
            phone_number = self._normalize_or_fail(phone_number)
            if User.objects.filter(phone_number=phone_number).exists():
                raise CommandError(
                    f"A user with phone number {phone_number} already exists."
                )

        with transaction.atomic():
            user = User.objects.create_superuser(phone_number, password=password)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded superuser: phone={user.phone_number} password={password}"
            )
        )

    @staticmethod
    def _normalize_or_fail(phone_number):
        try:
            return normalize_phone_number(phone_number)
        except ValidationError as exc:
            raise CommandError(
                f"Invalid phone number: {'; '.join(exc.messages)}"
            ) from exc

    def _unique_random_phone_number(self):
        for _ in range(MAX_PHONE_ATTEMPTS):
            phone_number = self._generate_phone_number()
            if not User.objects.filter(phone_number=phone_number).exists():
                return phone_number
        raise CommandError(
            f"Could not find an unused phone number in {MAX_PHONE_ATTEMPTS} attempts."
        )

    @staticmethod
    def _generate_phone_number():
        """Return a random, valid 09XXXXXXXXX number from a real operator prefix."""
        tail = "".join(random.choices("0123456789", k=7))
        return random.choice(_OPERATOR_PREFIXES) + tail
