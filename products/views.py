from django.db.models import Prefetch, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from products.models import Category, Product, Subcategory, resolve_reference_subcategory
from products.serializers import (
    CategorySerializer,
    ProductDetailSerializer,
    ProductSerializer,
    SubcategoryDetailSerializer,
    SubcategorySerializer,
)


class ProductPagination(PageNumberPagination):
    """Fixed-size catalog paging: 8 products per page.

    The page size is fixed server-side (clients cannot override it through
    query parameters); DRF's page links carry the original query string,
    so filters such as ?subcategory= stay active on every page.
    """

    page_size = 8
    page_size_query_param = None


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Public product catalog.

    Filters: ?category=<id>, ?subcategory=<id>, ?q=<text>.
    The category/subcategory filters match any of the product's (many)
    categories/subcategories.
    """

    serializer_class = ProductSerializer
    pagination_class = ProductPagination

    def get_queryset(self):
        queryset = Product.objects.all().prefetch_related(
            "categories", "subcategories"
        )
        # Query-parameter filters apply to the catalog list; the detail
        # view resolves its own reference subcategory (?subcategory= is
        # validated there instead of filtering the queryset).
        if self.action == "list":
            params = self.request.query_params
            category = params.get("category")
            subcategory = params.get("subcategory")
            search = params.get("q", "").strip()
            # Non-numeric filter values match nothing instead of crashing
            # the ORM with a ValueError (which would surface as a 500).
            if category and category.isdigit():
                queryset = queryset.filter(categories__id=category).distinct()
            elif category:
                queryset = queryset.none()
            if subcategory and subcategory.isdigit():
                queryset = queryset.filter(subcategories__id=subcategory).distinct()
            elif subcategory:
                queryset = queryset.none()
            if search:
                queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        # Stable ordering: created_at alone may tie, which lets rows
        # duplicate or disappear between sequential pages.
        return queryset.order_by("-created_at", "-id")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductSerializer

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        context = self.get_serializer_context()
        context["reference_subcategory"] = self._reference_subcategory(product)
        serializer = self.get_serializer(
            product,
            context=context,
        )
        return Response(serializer.data)

    def _reference_subcategory(self, product):
        """Resolve the subcategory whose attributes apply to this detail
        through the shared, never-guessing resolver (see
        products.models.resolve_reference_subcategory)."""
        try:
            return resolve_reference_subcategory(
                product, self.request.query_params.get("subcategory")
            )
        except ValueError as exc:
            raise ValidationError({"subcategory": str(exc)})


class SubcategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public subcategory list/detail. Filter: ?category=<id>"""

    pagination_class = None

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SubcategoryDetailSerializer
        return SubcategorySerializer

    def get_queryset(self):
        queryset = Subcategory.objects.filter(is_active=True).select_related("category")
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "products",
                    queryset=Product.objects.all().prefetch_related(
                        "categories", "subcategories"
                    ),
                )
            )
        category = self.request.query_params.get("category")
        # Non-numeric values match nothing instead of crashing the ORM.
        if category and category.isdigit():
            queryset = queryset.filter(category_id=category)
        elif category:
            queryset = queryset.none()
        return queryset


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public category list/detail with nested subcategories."""

    serializer_class = CategorySerializer
    queryset = Category.objects.filter(is_active=True).prefetch_related("subcategories")

    @action(detail=True, methods=["get"])
    def subcategories(self, request, pk=None):
        subcategories = self.get_object().subcategories.filter(is_active=True)
        serializer = SubcategorySerializer(subcategories, many=True)
        return Response(serializer.data)


class BestSellerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Public 'Best Sellers' showcase (GET /api/v1/best-sellers/).

    The list is curated manually by staff in Django Admin (products + a
    position number, lower shows first). Returned flat as product objects,
    in position order, unpaginated. Inactive products are included with
    ``is_active=False`` so the storefront can show them as unavailable.
    """

    serializer_class = ProductSerializer
    pagination_class = None

    def get_queryset(self):
        # Products that have been curated as best sellers, ordered by the
        # BestSeller position; Product instances so ProductSerializer works
        # directly on them.
        return (
            Product.objects.filter(best_seller__isnull=False)
            .prefetch_related("categories", "subcategories")
            .order_by("best_seller__position", "-best_seller__created_at")
        )
