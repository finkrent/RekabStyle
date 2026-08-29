from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from products.models import Category, Product, Subcategory
from products.serializers import CategorySerializer, ProductSerializer, SubcategorySerializer


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Public product catalog.

    Filters: ?category=<id>, ?subcategory=<id>, ?search=<text>
    """

    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True).select_related("category", "subcategory")
        params = self.request.query_params
        category = params.get("category")
        subcategory = params.get("subcategory")
        search = params.get("search")
        if category:
            queryset = queryset.filter(category_id=category)
        if subcategory:
            queryset = queryset.filter(subcategory_id=subcategory)
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
