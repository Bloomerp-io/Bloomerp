from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from django.test import SimpleTestCase

from bloomerp.tests.base import e2e_test_case as e2e


class E2EActionHelperTests(SimpleTestCase):
    def setUp(self) -> None:
        self.test_case = e2e.BloomerpE2ETestCase()
        self.test_case.page = MagicMock()

    def test_back_refresh_mimics_browser_back_with_optional_validator(
        self,
    ) -> None:
        validator = Mock()

        action = self.test_case.back_refresh(validator)

        self.assertIsInstance(action, e2e.E2EAction)
        self.assertIs(action.validators, validator)
        self.assertEqual(action.name, "Go back")

        action.execute()
        self.test_case._run_action_validators(action)

        self.test_case.page.expect_request.assert_called_once()
        request_matcher = self.test_case.page.expect_request.call_args.args[0]
        self.test_case.page.url = "http://testserver/files/?folder_id=2"
        self.assertTrue(
            request_matcher(
                SimpleNamespace(
                    resource_type="xhr",
                    url="http://testserver/files/?folder_id=2",
                )
            )
        )
        self.assertFalse(
            request_matcher(
                SimpleNamespace(
                    resource_type="xhr",
                    url="http://testserver/files/?folder_id=3",
                )
            )
        )
        self.assertFalse(
            request_matcher(
                SimpleNamespace(
                    resource_type="document",
                    url="http://testserver/files/?folder_id=2",
                )
            )
        )
        self.test_case.page.go_back.assert_called_once_with()
        self.test_case.page.reload.assert_not_called()
        validator.assert_called_once_with()

    def test_page_refresh_returns_action_with_optional_validators(self) -> None:
        validators = [Mock(), Mock()]

        action = self.test_case.page_refresh(validators)

        self.assertIsInstance(action, e2e.E2EAction)
        self.assertIs(action.validators, validators)
        self.assertEqual(action.name, "Refresh page")

        action.execute()
        self.test_case._run_action_validators(action)

        self.test_case.page.reload.assert_called_once_with(
            wait_until="domcontentloaded"
        )
        for validator in validators:
            validator.assert_called_once_with()

    def test_refresh_actions_default_to_no_validators(self) -> None:
        self.assertIsNone(self.test_case.back_refresh().validators)
        self.assertIsNone(self.test_case.page_refresh().validators)
