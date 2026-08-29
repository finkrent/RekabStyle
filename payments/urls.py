from django.urls import path

from payments import views

urlpatterns = [
    path("initiate/", views.InitiatePaymentView.as_view(), name="payment-initiate"),
    path("callback/", views.PaymentCallbackView.as_view(), name="payment-callback"),
    path("verify/", views.PaymentVerifyView.as_view(), name="payment-verify"),
]
