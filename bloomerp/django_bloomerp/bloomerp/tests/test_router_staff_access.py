from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.views import View

from bloomerp.config.definition import BloomerpConfig
from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.utils.users import create_admin, create_normal_user


def sample_function_view(request, *args, **kwargs):
    return HttpResponse("ok")


class PublicClassView(View):
    require_staff_for_access = False

    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class BloomerpRouteStaffAccessTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.admin_user = create_admin()
        self.normal_user = create_normal_user()

    def _build_callable(self, view, **register_kwargs):
        registry = BloomerpRouteRegistry()
        registry.register(path="/test/", **register_kwargs)(view)
        route = registry.routes[0]
        return registry._build_view_callable(route, registry._get_route_kwargs(route))

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_staff_required_by_default_for_staff_user(self):
        view_callable = self._build_callable(sample_function_view)

        request = self.factory.get("/test/")
        request.user = self.admin_user
        response = view_callable(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_authenticated_non_staff_is_denied_by_default(self):
        view_callable = self._build_callable(sample_function_view)

        request = self.factory.get("/test/")
        request.user = self.normal_user

        with self.assertRaises(PermissionDenied):
            view_callable(request)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_anonymous_user_is_redirected_to_login(self):
        view_callable = self._build_callable(sample_function_view)

        request = self.factory.get("/test/")
        request.user = AnonymousUser()
        response = view_callable(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=False))
    def test_global_setting_can_disable_staff_requirement(self):
        view_callable = self._build_callable(sample_function_view)

        request = self.factory.get("/test/")
        request.user = self.normal_user
        response = view_callable(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_register_override_can_allow_non_staff_access(self):
        view_callable = self._build_callable(
            sample_function_view,
            require_staff_for_access=False,
        )

        request = self.factory.get("/test/")
        request.user = self.normal_user
        response = view_callable(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_view_attribute_override_can_allow_non_staff_access(self):
        view_callable = self._build_callable(PublicClassView)

        request = self.factory.get("/test/")
        request.user = self.normal_user
        response = view_callable(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(BLOOMERP_CONFIG=BloomerpConfig(require_staff_for_access=True))
    def test_register_override_takes_precedence_over_view_attribute(self):
        view_callable = self._build_callable(
            PublicClassView,
            require_staff_for_access=True,
        )

        request = self.factory.get("/test/")
        request.user = self.normal_user

        with self.assertRaises(PermissionDenied):
            view_callable(request)
