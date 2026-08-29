from django.conf import settings
from django.db import models


class Payment(models.Model):
    """A Zibal payment attempt for an order."""

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField("Amount (Toman)", max_digits=14, decimal_places=0)
    authority = models.CharField("Zibal track ID", max_length=64, blank=True, db_index=True)
    status = models.CharField(
        "Status", max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    result_code = models.IntegerField("Gateway result code", null=True, blank=True)
    paid_at = models.DateTimeField("Paid at", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Payment #{self.pk} for order {self.order.order_number} ({self.status})"
