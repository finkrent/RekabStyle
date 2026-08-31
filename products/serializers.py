from rest_framework import serializers

from products.models import Category, Product, Subcategory


class ProductSerializer(serializers.ModelSerializer):
    categories = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    category_names = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name", source="categories"
    )
    subcategories = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    subcategory_names = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name", source="subcategories"
    )


    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "image",
            "categories",
            "category_names",
            "subcategories",
            "subcategory_names",


            "is_active",
            "created_at",
        ]


class SubcategorySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Subcategory
        fields = ["id", "name", "category", "category_name", "is_active"]


class CategorySerializer(serializers.ModelSerializer):
    subcategories = SubcategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "is_active", "subcategories", "created_at"]
