import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from orders.models import CustomDesign, CustomDesignImage, Order
from payments.models import Payment

from .tests import OrderTestBase


class CleanupOrdersCommandTests(OrderTestBase):
    def _age_order(self, order, *, days=0, hours=0):
        created_at = timezone.now() - timedelta(days=days, hours=hours)
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        order.refresh_from_db()
        return order

    def test_deletes_only_expired_uninitiated_and_failed_orders(self):
        user, address = self._make_complete_user()
        stale_uninitiated = self._age_order(
            self._create_order(user, address), hours=25
        )
        recent_uninitiated = self._create_order(user, address)
        stale_attempted = self._age_order(
            self._create_order(user, address), hours=25
        )
        Payment.objects.create(order=stale_attempted, amount=stale_attempted.total_price)
        stale_failed = self._age_order(self._create_order(user, address), days=31)
        stale_failed.status = Order.STATUS_FAILED
        stale_failed.save(update_fields=["status"])
        Order.objects.filter(pk=stale_failed.pk).update(
            updated_at=timezone.now() - timedelta(days=31)
        )
        failed_payment = Payment.objects.create(
            order=stale_failed,
            amount=stale_failed.total_price,
            status=Payment.STATUS_FAILED,
        )
        recent_failed = self._age_order(
            self._create_order(user, address), days=60
        )
        recent_failed.status = Order.STATUS_FAILED
        recent_failed.save(update_fields=["status"])
        paid = self._age_order(self._create_order(user, address), days=60)
        paid.status = Order.STATUS_PAID
        paid.save(update_fields=["status"])

        call_command("cleanup_orders")

        self.assertFalse(Order.objects.filter(pk=stale_uninitiated.pk).exists())
        self.assertTrue(Order.objects.filter(pk=recent_uninitiated.pk).exists())
        self.assertTrue(Order.objects.filter(pk=stale_attempted.pk).exists())
        self.assertFalse(Order.objects.filter(pk=stale_failed.pk).exists())
        self.assertFalse(Payment.objects.filter(pk=failed_payment.pk).exists())
        self.assertTrue(Order.objects.filter(pk=recent_failed.pk).exists())
        self.assertTrue(Order.objects.filter(pk=paid.pk).exists())

    def test_cleanup_deletes_custom_design_files(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                user, address = self._make_complete_user()
                order = self._age_order(self._create_order(user, address), days=31)
                order.status = Order.STATUS_FAILED
                order.save(update_fields=["status"])
                Order.objects.filter(pk=order.pk).update(
                    updated_at=timezone.now() - timedelta(days=31)
                )
                design = CustomDesign.objects.create(
                    order=order, description="Old design"
                )
                image = CustomDesignImage.objects.create(design=design, position=0)
                image.image.save("old-design.png", ContentFile(b"image bytes"))
                image_path = Path(media_root, image.image.name)
                self.assertTrue(image_path.exists())

                call_command("cleanup_orders")

                self.assertFalse(image_path.exists())
                self.assertFalse(Order.objects.filter(pk=order.pk).exists())
