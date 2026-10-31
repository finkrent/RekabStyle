"""Tests for the idempotent seed_superuser management command."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

User = get_user_model()

RANDOM_PHONE_TARGET = (
    "accounts.management.commands.seed_superuser.Command._generate_phone_number"
)


def call_seed(*args, **kwargs):
    """Run the seed command and return its stdout output."""
    out = io.StringIO()
    call_command("seed_superuser", *args, stdout=out, **kwargs)
    return out.getvalue()


@override_settings(DEBUG=True)
class SeedSuperuserCommandTests(TestCase):
    def test_creates_superuser_with_random_phone_and_password(self):
        self.assertEqual(User.objects.count(), 0)

        output = call_seed()

        superusers = User.objects.filter(is_superuser=True)
        self.assertEqual(superusers.count(), 1)
        superuser = superusers.get()
        self.assertTrue(superuser.is_staff)
        self.assertRegex(superuser.phone_number, r"^09\d{9}$")
        self.assertTrue(superuser.check_password("123456"))
        # The generated login must be reported so the operator can use it.
        self.assertIn(superuser.phone_number, output)

    def test_is_idempotent_when_run_ten_times(self):
        for _ in range(10):
            call_seed()

        self.assertEqual(User.objects.count(), 1)
        superuser = User.objects.get()
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.check_password("123456"))

    def test_skips_when_superuser_already_exists(self):
        User.objects.create_superuser("09121234567", password="real-secret")

        output = call_seed()

        self.assertEqual(User.objects.count(), 1)
        superuser = User.objects.get()
        self.assertEqual(superuser.phone_number, "09121234567")
        # The existing account is left untouched (password not reset).
        self.assertTrue(superuser.check_password("real-secret"))
        self.assertIn("09121234567", output)

    def test_generated_phone_avoids_collision_with_existing_user(self):
        User.objects.create_user("09129999999", password="user-pass")
        with patch(
            RANDOM_PHONE_TARGET, side_effect=["09129999999", "09128888888"]
        ):
            call_seed()

        self.assertEqual(User.objects.count(), 2)
        superuser = User.objects.get(is_superuser=True)
        self.assertEqual(superuser.phone_number, "09128888888")

    def test_explicit_phone_number_option_wins_over_random(self):
        call_seed(phone_number="09123456789")

        superuser = User.objects.get(is_superuser=True)
        self.assertEqual(superuser.phone_number, "09123456789")
        self.assertTrue(superuser.check_password("123456"))

    def test_explicit_phone_number_conflicting_with_existing_user_fails(self):
        User.objects.create_user("09121111111", password="user-pass")

        with self.assertRaises(CommandError):
            call_seed(phone_number="09121111111")

        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(User.objects.filter(is_superuser=True).exists())


@override_settings(DEBUG=False)
class SeedSuperuserProductionGuardTests(TestCase):
    def test_refuses_to_run_when_debug_is_false(self):
        with self.assertRaises(CommandError):
            call_seed()

        self.assertEqual(User.objects.count(), 0)

    def test_force_flag_allows_running_when_debug_is_false(self):
        call_seed("--force")

        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
