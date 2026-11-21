from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import Address, OtpCode, TermsAcceptance, User


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
    readonly_fields = (
        "last_login",
        "date_joined",
        "rules_accepted_at",
        "rules_accepted_version",
    )
    inlines = [AddressInline]
    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "national_id")},
        ),
        (
            "Website rules",
            {"fields": ("rules_accepted_at", "rules_accepted_version")},
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

    @admin.display(description="Rules accepted at")
    def rules_accepted_at(self, obj):
        acceptance = obj.latest_terms_acceptance if obj else None
        return acceptance.accepted_at if acceptance else None

    @admin.display(description="Rules version")
    def rules_accepted_version(self, obj):
        acceptance = obj.latest_terms_acceptance if obj else None
        return acceptance.terms_version if acceptance else None


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user", "postal_code", "short_address", "created_at")
    search_fields = ("user__phone_number", "user__national_id", "address", "postal_code")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Address")
    def short_address(self, obj):
        return obj.address[:60]


@admin.register(TermsAcceptance)
class TermsAcceptanceAdmin(admin.ModelAdmin):
    """Read-only legal evidence of accepted Website Rules and Regulations."""

    list_display = ("user", "national_id", "terms_version", "accepted_at", "ip_address")
    list_filter = ("terms_version",)
    search_fields = ("user__phone_number", "national_id")
    date_hierarchy = "accepted_at"
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "national_id",
        "terms_version",
        "accepted_at",
        "ip_address",
        "user_agent",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "created_at", "expires_at", "attempt_count", "is_used")
    list_filter = ("is_used",)
    search_fields = ("phone_number",)
    readonly_fields = ("phone_number", "code_hash", "created_at", "expires_at", "attempt_count", "is_used")

    def has_add_permission(self, request):
        return False
