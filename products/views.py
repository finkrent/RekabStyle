from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from products.models import Category, Product, Subcategory
from products.serializers import CategorySerializer, ProductSerializer, SubcategorySerializer


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Public product catalog.

    Filters: ?category=<id>, ?subcategory=<id>, ?search=<text>.
    The category/subcategory filters match any of the product's (many)
    categories/subcategories.
    """

    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True).prefetch_related(
            "categories", "subcategories"
        )
        params = self.request.query_params
        category = params.get("category")
        subcategory = params.get("subcategory")
        search = params.get("search")
        if category:
            queryset = queryset.filter(categories__id=category).distinct()
        if subcategory:
            queryset = queryset.filter(subcategories__id=subcategory).distinct()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return queryset


class SubcategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public subcategory list/detail. Filter: ?category=<id>"""

    serializer_class = SubcategorySerializer

    def get_queryset(self):
        queryset = Subcategory.objects.filter(is_active=True).select_related("category")
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category_id=category)
        return queryset


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public category list/detail with nested subcategories."""

    serializer_class = CategorySerializer
    queryset = Category.objects.filter(is_active=True).prefetch_related("subcategories")

    @action(detail=True, methods=["get"])
    def subcategories(self, request, pk=None):
        subcategories = self.get_object().subcategories.filter(is_active=True)
        page = self.paginate_queryset(subcategories)
        serializer = SubcategorySerializer(
            page if page is not None else subcategories, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class BestSellerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Public 'Best Sellers' showcase (GET /api/v1/best-sellers/).

    The list is curated manually by staff in Django Admin (products + a
    position number, lower shows first). Returned flat as product objects,
    in position order, unpaginated. Inactive products are never exposed.
    """

    serializer_class = ProductSerializer
    pagination_class = None

    def get_queryset(self):
        # Products that have been curated as best sellers, ordered by the
        # BestSeller position; Product instances so ProductSerializer works
        # directly on them.
        return (
            Product.objects.filter(is_active=True, best_seller__isnull=False)
            .prefetch_related("categories", "subcategories")
            .order_by("best_seller__position", "-best_seller__created_at")
        )
