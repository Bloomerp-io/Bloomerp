from django.test import override_settings

from bloomerp.config.definition import BloomerpAuthSettings, BloomerpConfig, InteractiveAuthSettings
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels, ExpectedResult, RequestScenario
from bloomerp.tests.base.request_test_case_mixin import RequestTestCaseMixin


class TestBrowserLoginView(RequestTestCaseMixin, BaseBloomerpTestCaseWithModels):
    view_name = "login"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="Email can be configured as browser login identifier",
                description=(
                    "UC: Interactive authentication uses email as its login identifier.\n"
                    "Expected Result: Posting the user's email signs them into the browser session."
                ),
                method="POST",
                data={"username": "johndoe@example.com", "password": "testpass123"},
                prepare=self.enable_email_login,
                cleanup=self.disable_settings_override,
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=lambda _response: (
                        self.client.session.get("_auth_user_id") == str(self.normal_user.pk)
                    ),
                ),
            )
        ]

    def enable_email_login(self, _scenario):
        self.settings_override = override_settings(
            BLOOMERP_CONFIG=BloomerpConfig(
                auto_generate_api_endpoints=True,
                auth=BloomerpAuthSettings(
                    interactive=InteractiveAuthSettings(login_identifier="email")
                ),
            )
        )
        self.settings_override.enable()

    def disable_settings_override(self, _scenario):
        self.settings_override.disable()
