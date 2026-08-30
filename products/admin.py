from django.contrib import admin

from products.models import BestSeller, Category, Product, Subcategory


class SubcategoryInline(admin.TabularInline):
    model = Subcategory
    extra = 1


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
    list_display = ("name", "price", "category", "subcategory", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
    list_editable = ("price", "is_active")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category", "subcategory")


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
