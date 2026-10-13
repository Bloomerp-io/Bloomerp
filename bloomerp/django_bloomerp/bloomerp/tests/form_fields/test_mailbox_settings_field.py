"""Validate the compound values used by the mailbox mapping editor."""

from typing import Any
from django.core.exceptions import ValidationError
from bloomerp.form_fields.mailbox_settings_field import MailboxSettingsField
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    FormFieldScenario,
    ExpectedFormFieldException,
)


class TestMailboxSettingsField(BloomerpFormFieldTestCase[MailboxSettingsField]):
    field_class = MailboxSettingsField

    def valid_settings(self, value: Any) -> bool:
        """Verify role booleans and optional presentation values are cleaned together."""
        return value == {
            "label": "Incoming",
            "sent_folder": False,
            "main_folder": True,
            "color": "#2563eb",
        }

    def get_test_scenarios(self) -> list[FormFieldScenario[MailboxSettingsField]]:
        """Cover browser extraction, persisted values and invalid presentation data."""
        failure = [ExpectedFormFieldException(phase="clean", exception=ValidationError)]
        return [
            FormFieldScenario(
                name="Clean compound browser values",
                clean_value=["Incoming", False, "on", "#2563eb"],
                clean_result_validators=self.valid_settings,
            ),
            FormFieldScenario(
                name="Reject empty label",
                clean_value=["", False, True, ""],
                expected_exceptions=failure,
            ),
            FormFieldScenario(
                name="Reject arbitrary CSS",
                clean_value=["Incoming", False, True, "red;display:none"],
                expected_exceptions=failure,
            ),
        ]
