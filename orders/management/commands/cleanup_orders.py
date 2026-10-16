from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from orders.models import CustomDesignImage, Order
from payments.models import Payment


class Command(BaseCommand):
    help = (
        "Delete pending orders without payment attempts after 24 hours and "
        "failed orders after 30 days."
    )

    def add_arguments(self, parser):
        parser.add_argument("--pending-hours", type=int, default=24)
        parser.add_argument("--failed-days", type=int, default=30)

    def handle(self, *args, **options):
        pending_hours = options["pending_hours"]
        failed_days = options["failed_days"]
        if pending_hours < 1 or failed_days < 1:
            raise CommandError("Retention periods must be positive integers.")

        now = timezone.now()
        deleted_pending = self._delete_expired_orders(
            status=Order.STATUS_PENDING,
            age_field="created_at",
            cutoff=now - timedelta(hours=pending_hours),
            require_no_payments=True,
        )
        deleted_failed = self._delete_expired_orders(
            status=Order.STATUS_FAILED,
            age_field="updated_at",
            cutoff=now - timedelta(days=failed_days),
            require_no_payments=False,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_pending} expired uninitiated pending orders and "
                f"{deleted_failed} expired failed orders."
            )
        )

    def _delete_expired_orders(
        self, *, status, age_field, cutoff, require_no_payments
    ):
        order_ids = Order.objects.filter(
            status=status, **{f"{age_field}__lt": cutoff}
        )
        if require_no_payments:
            order_ids = order_ids.filter(payments__isnull=True)
        else:
            order_ids = order_ids.exclude(
                payments__status=Payment.STATUS_SUCCESS
            ).distinct()

        deleted_count = 0
        for order_id in order_ids.values_list("pk", flat=True).iterator():
            if self._delete_order(
                order_id,
                status=status,
                age_field=age_field,
                cutoff=cutoff,
                require_no_payments=require_no_payments,
            ):
                deleted_count += 1
        return deleted_count

    def _delete_order(
        self, order_id, *, status, age_field, cutoff, require_no_payments
    ):
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .filter(
                    pk=order_id,
                    status=status,
                    **{f"{age_field}__lt": cutoff},
                )
                .first()
            )
            if order is None:
                return False
            if require_no_payments and order.payments.exists():
                return False
            if (
                not require_no_payments
                and order.payments.filter(status=Payment.STATUS_SUCCESS).exists()
            ):
                return False

            image_names = list(
                CustomDesignImage.objects.filter(design__order=order).values_list(
                    "image", flat=True
                )
            )
            Payment.objects.filter(order=order).delete()
            order.delete()

        storage = CustomDesignImage._meta.get_field("image").storage
        for image_name in image_names:
            if image_name:
                storage.delete(image_name)
        return True
