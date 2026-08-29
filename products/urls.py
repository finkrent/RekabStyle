from rest_framework.routers import DefaultRouter

from products import views

router = DefaultRouter()
router.register("products", views.ProductViewSet, basename="product")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("subcategories", views.SubcategoryViewSet, basename="subcategory")

urlpatterns = router.urls
