from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.models import (
    AttributeChoice,
    BestSeller,
    Category,
    Product,
    ProductAttribute,
    Subcategory,
)


class SubcategoryInline(admin.TabularInline):
    model = Subcategory
    extra = 1


class ProductAdminForm(forms.ModelForm):
    """Validates the (M2M) category/subcategory assignments at form time,
    because model-level M2M validation cannot run on unsaved instances (the
    M2M values live in the form, not on the instance yet)."""

    class Meta:
        model = Product
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        self.instance.validate_subcategories(
            cleaned_data.get("categories") or (),
            cleaned_data.get("subcategories") or (),
        )
        return cleaned_data


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [SubcategoryInline]


class ProductAttributeInline(admin.TabularInline):
    """Attributes managed directly on the subcategory admin page."""

    model = ProductAttribute
    fields = (
        "key",
        "name",
        "input_type",
        "is_required",
        "is_active",
        "choices_link",
    )
    readonly_fields = ("choices_link",)
    extra = 1

    @admin.display(description="Choices")
    def choices_link(self, obj):
        if not obj or not obj.pk:
            return "Save the attribute first"
        if obj.input_type != ProductAttribute.INPUT_SELECT:
            return "Select attributes only"
        url = reverse("admin:products_productattribute_change", args=(obj.pk,))
        return format_html('<a href="{}">Manage choices</a>', url)


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    fields = ("category", "name", "slug", "is_active")
    list_display = ("name", "category", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    list_select_related = ("category",)
    inlines = [ProductAttributeInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    fields = (
        "name",
        "slug",
        "description",
        "price",
        "image",
        "categories",
        "subcategories",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_display = ("name", "price", "categories_summary", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    list_editable = ("price", "is_active")
    readonly_fields = ("created_at", "updated_at")
    filter_horizontal = ("categories", "subcategories")

    @admin.display(description="Categories")
    def categories_summary(self, obj):
        return ", ".join(category.name for category in obj.categories.all())

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("categories")


@admin.register(BestSeller)
class BestSellerAdmin(admin.ModelAdmin):
    """Curated 'Best Sellers' showcase: staff pick existing products and
    order them by typing a position number (lower shows first)."""

    list_display = ("product", "position", "created_at")
    list_editable = ("position",)
    list_display_links = ("product",)
    autocomplete_fields = ("product",)
    ordering = ("position", "-created_at")
    list_select_related = ("product",)


class AttributeChoiceInline(admin.TabularInline):
    """Choices of one attribute: key, label, and the admin-set price delta."""

    model = AttributeChoice
    extra = 1


@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    """Generic subcategory attributes: enable/disable, required flag,
    input type, and their selectable choices."""

    list_display = ("key", "name", "subcategory", "input_type", "is_required", "is_active")
    list_filter = ("input_type", "is_required", "is_active", "subcategory")
    search_fields = ("key", "name", "subcategory__name")
    list_select_related = ("subcategory",)
    inlines = [AttributeChoiceInline]
