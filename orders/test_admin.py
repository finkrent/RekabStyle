from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from orders.admin import OrderItemOptionAdmin
from orders.models import Order, OrderItemOption
from products.models import AttributeChoice, ProductAttribute

from .tests import OrderTestBase

User = get_user_model()


class OrderAdminDeletionTests(OrderTestBase):
    def _order_with_option(self, user, address):
        order = self._create_order(user, address)
        attribute = ProductAttribute.objects.create(
            key="color", name="Color", input_type="select"
        )
        choice = AttributeChoice.objects.create(
            attribute=attribute, key="red", label="Red", price_delta=0
        )
        option = OrderItemOption.objects.create(
            item=order.items.get(),
            attribute=attribute,
            attribute_key="color",
            attribute_label="Color",
            input_type="select",
            choice=choice,
            choice_key="red",
            choice_label="Red",
            price_delta=0,
        )
        return order, option

    def test_superuser_can_delete_an_order_with_item_options(self):
        user, address = self._make_complete_user()
        order, option = self._order_with_option(user, address)
        superuser = User.objects.create_superuser(
            phone_number="09111111111", password="admin-pass-123"
        )
        self.client.force_login(superuser)
        url = reverse("admin:orders_order_delete", args=[order.pk])

        confirmation = self.client.get(url)
        self.assertEqual(confirmation.status_code, 200)
        response = self.client.post(url, {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        self.assertFalse(OrderItemOption.objects.filter(pk=option.pk).exists())

    def test_non_superuser_staff_cannot_delete_item_options(self):
        staff = User.objects.create_user(
            phone_number="09111111111", is_staff=True
        )
        request = RequestFactory().get("/admin/")
        request.user = staff
        model_admin = OrderItemOptionAdmin(OrderItemOption, admin.site)

        self.assertFalse(model_admin.has_delete_permission(request))
