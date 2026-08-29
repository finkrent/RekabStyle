from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import Address, OtpCode, User


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "phone_number",
        "national_id",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_staff", "is_active")
    search_fields = ("phone_number", "national_id", "first_name", "last_name")
    ordering = ("-date_joined",)
    readonly_fields = ("last_login", "date_joined")
    inlines = [AddressInline]
    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "national_id")},
        ),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone_number", "national_id", "password1", "password2"),
            },
        ),
    )


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user", "postal_code", "short_address", "created_at")
    search_fields = ("user__phone_number", "user__national_id", "address", "postal_code")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Address")
    def short_address(self, obj):
        return obj.address[:60]


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "created_at", "expires_at", "attempt_count", "is_used")
    list_filter = ("is_used",)
    search_fields = ("phone_number",)
    readonly_fields = ("phone_number", "code_hash", "created_at", "expires_at", "attempt_count", "is_used")

    def has_add_permission(self, request):
        return False
