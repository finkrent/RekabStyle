from django.contrib import admin

from payments.models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "order_number", "amount", "status", "authority", "paid_at", "created_at")
    list_filter = ("status",)
    search_fields = ("authority", "order__order_number", "order__user__phone_number")
    readonly_fields = (
        "order",
        "amount",
        "authority",
        "status",
        "result_code",
        "paid_at",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Order", ordering="order__order_number")
    def order_number(self, obj):
        return obj.order.order_number
