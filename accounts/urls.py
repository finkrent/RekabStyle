from django.urls import path

from accounts import views
from accounts.views import TokenRefreshView

urlpatterns = [
    path("request-otp/", views.RequestOtpView.as_view(), name="request-otp"),
    path("verify-otp/", views.VerifyOtpView.as_view(), name="verify-otp"),
    path(
        "complete-registration/",
        views.CompleteRegistrationView.as_view(),
        name="complete-registration",
    ),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("addresses/", views.AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<int:pk>/", views.AddressDetailView.as_view(), name="address-detail"),
]
