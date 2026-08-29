from django.contrib import admin

from products.models import Category, Product, Subcategory


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
