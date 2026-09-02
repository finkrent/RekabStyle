from django.contrib import admin

from orders.models import CustomDesign, CustomDesignImage, Order, OrderItem
from payments.models import Payment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product_name", "unit_price", "total_price")


class CustomDesignInline(admin.TabularInline):
    """The custom-design request itself; its images are managed on the
    CustomDesign admin page (Django does not support nested inlines)."""

    model = CustomDesign
    extra = 0
    max_num = 1
    readonly_fields = ("surcharge_percent", "created_at")


class PaymentInline(admin.StackedInline):
    model = Payment
    extra = 0
    can_delete = False
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

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer_phone", "status", "total_price", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("order_number", "user__phone_number", "user__national_id")
    readonly_fields = ("order_number", "total_price", "shipping_address", "shipping_postal_code", "created_at", "updated_at")
    inlines = [OrderItemInline, CustomDesignInline, PaymentInline]

    @admin.display(description="Customer phone", ordering="user__phone_number")
    def customer_phone(self, obj):
        return obj.user.phone_number


class CustomDesignImageInline(admin.TabularInline):
    model = CustomDesignImage
    extra = 0


@admin.register(CustomDesign)
class CustomDesignAdmin(admin.ModelAdmin):
    list_display = ("order", "surcharge_percent", "created_at")
    search_fields = ("order__order_number", "order__user__phone_number")
    readonly_fields = ("order", "surcharge_percent", "created_at")
    inlines = [CustomDesignImageInline]
