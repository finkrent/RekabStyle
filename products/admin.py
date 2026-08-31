from django import forms
from django.contrib import admin

from products.models import BestSeller, Category, Product, Subcategory


class SubcategoryInline(admin.TabularInline):
    model = Subcategory
    extra = 1


class ProductAdminForm(forms.ModelForm):
    """Validates the additional (M2M) category/subcategory assignments at
    form time, because model-level M2M validation cannot run on unsaved
    instances (the M2M values live in the form, not the instance yet)."""

    class Meta:
        model = Product
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        product = self.instance
        product.validate_category_relations(
            cleaned_data.get("additional_categories") or (),
            cleaned_data.get("additional_subcategories") or (),
        )
        return cleaned_data


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [SubcategoryInline]


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    list_select_related = ("category",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ("name", "price", "category", "subcategory", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
    list_editable = ("price", "is_active")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category", "subcategory")
    filter_horizontal = ("additional_categories", "additional_subcategories")


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
