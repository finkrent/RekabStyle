from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.models import AttributeChoice, Category, Product, ProductAttribute, Subcategory


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
            "slug",
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
        fields = ["id", "name", "slug", "category", "category_name", "is_active"]


class SubcategoryDetailSerializer(SubcategorySerializer):
    products = ProductSerializer(many=True, read_only=True)

    class Meta(SubcategorySerializer.Meta):
        fields = [*SubcategorySerializer.Meta.fields, "products"]


class CategorySerializer(serializers.ModelSerializer):
    subcategories = SubcategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "is_active", "subcategories", "created_at"]


class AttributeChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeChoice
        fields = ["key", "label", "price_delta"]


class ProductOptionSerializer(serializers.ModelSerializer):
    """One product option: an active attribute of the reference subcategory.

    `select` attributes carry their `choices` (each with its price_delta);
    `text` attributes carry a fixed "0" price_delta and no choices.
    The non-model fields are declared for the schema; `to_representation`
    emits exactly one of `choices`/`price_delta` per attribute type.
    """

    label = serializers.CharField(source="name", read_only=True)
    type = serializers.CharField(source="input_type", read_only=True)
    required = serializers.BooleanField(source="is_required", read_only=True)
    choices = serializers.ListField(
        child=AttributeChoiceSerializer(), read_only=True, required=False
    )
    price_delta = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = ProductAttribute
        fields = ["key", "label", "type", "required", "choices", "price_delta"]

    def to_representation(self, instance):
        data = {
            "key": instance.key,
            "label": instance.name,
            "type": instance.input_type,
            "required": instance.is_required,
        }
        if instance.input_type == ProductAttribute.INPUT_SELECT:
            data["choices"] = AttributeChoiceSerializer(
                instance.choices.all(), many=True
            ).data
        else:
            data["price_delta"] = "0"
        return data


class ProductDetailSerializer(ProductSerializer):
    """Product detail plus the active attributes of the reference subcategory.

    The reference subcategory is resolved by the view (explicit
    ?subcategory=<id>, or the product's only subcategory) and passed through
    the serializer context as `reference_subcategory`; without one, `options`
    is an empty list.
    """

    options = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = [*ProductSerializer.Meta.fields, "options"]

    @extend_schema_field(ProductOptionSerializer(many=True))
    def get_options(self, obj):
        subcategory = self.context.get("reference_subcategory")
        if subcategory is None:
            return []
        return ProductOptionSerializer(
            subcategory.attributes.filter(is_active=True), many=True
        ).data
