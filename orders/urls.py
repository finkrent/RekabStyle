from django.urls import path

from orders import views

urlpatterns = [
    path("", views.OrderListCreateView.as_view(), name="order-list"),
    path("<int:pk>/", views.OrderDetailView.as_view(), name="order-detail"),
]
