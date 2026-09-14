from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TransactionTestCase, override_settings
from django.urls import path

from bloomerp.tests.base.request_test_case_mixin import (
    ExpectedResult,
    RequestScenario,
    RequestTestCaseMixin,
)


def prepared_request_view(request):
    return HttpResponse("ok")


urlpatterns = [
    path("prepared-request/", prepared_request_view, name="prepared_request"),
]


@override_settings(ROOT_URLCONF=__name__)
class RequestSetupIsolationTests(RequestTestCaseMixin, TransactionTestCase):
    view_name = "prepared_request"

    def setUp(self):
        super().setUp()
        self.cleanup_calls = []

    def get_test_scenarios(self) -> list[RequestScenario]:
        def create_marker(setup):
            get_user_model().objects.create(username="scenario-marker")

        def assert_marker_was_created(setup):
            self.assertTrue(
                get_user_model().objects.filter(username="scenario-marker").exists()
            )

        def assert_marker_was_rolled_back(setup):
            self.assertFalse(
                get_user_model().objects.filter(username="scenario-marker").exists()
            )
            self.assertEqual(self.cleanup_calls, ["second", "first"])

        return [
            RequestScenario(
                name="creates scenario-only data",
                prepare=[create_marker, assert_marker_was_created],
                cleanup=[
                    lambda setup: self.cleanup_calls.append("first"),
                    lambda setup: self.cleanup_calls.append("second"),
                ],
                expected=ExpectedResult(status_code=200),
            ),
            RequestScenario(
                name="starts without the previous scenario's data",
                prepare=assert_marker_was_rolled_back,
                expected=ExpectedResult(status_code=200),
            ),
        ]
