"""Tests for the idempotent seed_superuser management command."""
import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

User = get_user_model()

SEED_PHONE = "09123456789"
SEED_PASSWORD = "12345678"


def call_seed(*args, **kwargs):
    """Run the seed command and return its stdout output."""
    out = io.StringIO()
    call_command("seed_superuser", *args, stdout=out, **kwargs)
    return out.getvalue()


@override_settings(DEBUG=True)
class SeedSuperuserCommandTests(TestCase):
    def test_creates_fixed_superuser_with_password(self):
        self.assertEqual(User.objects.count(), 0)

        output = call_seed()

        superusers = User.objects.filter(is_superuser=True)
        self.assertEqual(superusers.count(), 1)
        superuser = superusers.get()
        self.assertEqual(superuser.phone_number, SEED_PHONE)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.check_password(SEED_PASSWORD))
        # The login must be reported so the operator can use it.
        self.assertIn(SEED_PHONE, output)

    def test_is_idempotent_when_run_ten_times(self):
        for _ in range(10):
            call_seed()

        self.assertEqual(User.objects.count(), 1)
        superuser = User.objects.get()
        self.assertEqual(superuser.phone_number, SEED_PHONE)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.check_password(SEED_PASSWORD))

    def test_skips_when_seed_superuser_already_exists(self):
        User.objects.create_superuser(SEED_PHONE, password="real-secret")

        output = call_seed()

        self.assertEqual(User.objects.count(), 1)
        # The existing account is left untouched (password not reset).
        self.assertTrue(User.objects.get().check_password("real-secret"))
        self.assertIn("skipping", output)

    def test_creates_seed_account_when_another_superuser_exists(self):
        User.objects.create_superuser("09146964851", password="other-secret")

        call_seed()

        self.assertEqual(User.objects.count(), 2)
        seed = User.objects.get(phone_number=SEED_PHONE)
        self.assertTrue(seed.is_superuser)
        self.assertTrue(seed.check_password(SEED_PASSWORD))

    def test_refuses_when_phone_belongs_to_regular_user(self):
        User.objects.create_user(SEED_PHONE, password="user-pass")

        with self.assertRaises(CommandError):
            call_seed()

        user = User.objects.get()
        self.assertFalse(user.is_superuser)
        # The existing account is left untouched.
        self.assertTrue(user.check_password("user-pass"))


@override_settings(DEBUG=False)
class SeedSuperuserProductionGuardTests(TestCase):
    def test_refuses_to_run_when_debug_is_false(self):
        with self.assertRaises(CommandError):
            call_seed()

        self.assertEqual(User.objects.count(), 0)

    def test_force_flag_allows_running_when_debug_is_false(self):
        call_seed("--force")

        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
