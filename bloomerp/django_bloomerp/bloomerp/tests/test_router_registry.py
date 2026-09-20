"""Tests for route registry behavior."""

from django.apps import apps
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.utils.users import create_admin


def sample_function_view(request, *args, **kwargs):
    return HttpResponse("ok")


def first_route_view(request, *args, **kwargs):
    return HttpResponse("first")


def second_route_view(request, *args, **kwargs):
    return HttpResponse("second")


class BloomerpRouteRegistryTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.admin_user = create_admin()

    def test_override_route_replaces_earlier_conflicting_route(self):
        registry = BloomerpRouteRegistry()
        registry.register(path="/same/", name="Same", url_name="same")(first_route_view)
        registry.register(path="/same/", name="Same", url_name="same", override=True)(second_route_view)

        self.assertEqual(len(registry.routes), 1)
        self.assertTrue(registry.routes[0].override)

        request = self.factory.get("/same/")
        request.user = self.admin_user
        response = registry.routes[0].view(request)

        self.assertEqual(response.content, b"second")

    def test_non_override_route_does_not_replace_earlier_override_route(self):
        registry = BloomerpRouteRegistry()
        registry.register(path="/same/", name="Same", url_name="same", override=True)(first_route_view)
        registry.register(path="/same/", name="Same", url_name="same")(second_route_view)

        self.assertEqual(len(registry.routes), 1)
        self.assertTrue(registry.routes[0].override)

        request = self.factory.get("/same/")
        request.user = self.admin_user
        response = registry.routes[0].view(request)

        self.assertEqual(response.content, b"first")

    def test_get_routes_by_app_returns_only_routes_owned_by_app(self):
        registry = BloomerpRouteRegistry()
        registry.register(path="/owned/", name="Owned")(sample_function_view)
        registry.register(path="/other/", name="Other")(second_route_view)
        registry.routes[1].owner_app_label = "another_app"

        routes = registry.get_routes_by_app(apps.get_app_config("bloomerp"))

        self.assertEqual([route.path for route in routes], ["/owned/"])
