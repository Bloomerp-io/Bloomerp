"""Exercise a compound editor nested inside the existing MappingWidget."""

from typing import Any
from bs4 import BeautifulSoup
from django import forms
from django.http import QueryDict
from bloomerp.widgets.mapping_widget import MappingWidget
from bloomerp.widgets.mailbox_settings_widget import MailboxSettingsWidget
from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetScenario, WidgetOperation


class TestMailboxSettingsWidget(BloomerpWidgetTestCase[MappingWidget]):
    widget_class = MappingWidget

    def compact_layout(self, widget: MappingWidget) -> None:
        """Use the mailbox-specific layout without changing general mapping widgets."""
        widget.template_name = "widgets/mailbox_mapping.html"

    def extract(self, widget: MappingWidget) -> Any:
        """Extract nested checkboxes and text inputs with their unique row names."""
        return widget.value_from_datadict(
            QueryDict(
                "mailboxes__rows=0&mailboxes__key_0=INBOX&mailboxes__value_0_0=Incoming&mailboxes__value_0_2=on&mailboxes__value_0_3=%232563eb"
            ),
            {},
            "mailboxes",
        )

    def valid_values(self, value: Any) -> bool:
        """Verify nested inputs retain their provider mailbox and boolean settings."""
        return value == [("INBOX", ["Incoming", False, True, "#2563eb"])]

    def render_mapping(self, widget: MappingWidget) -> str:
        """Render persisted settings in fixed mapping rows."""
        return widget.render(
            "mailboxes",
            {"INBOX": {"label": "Incoming", "main_folder": True}},
            attrs={"id": "id_mailboxes"},
        )

    def valid_html(self, value: Any) -> bool:
        """Check compact controls, accessible labels and optional color storage."""
        return all(
            fragment in value
            for fragment in [
                "Provider mailbox",
                'bloomerp-component="mailbox-settings"',
                'type="color"',
                'data-mailbox-color-clear',
                'data-mailbox-color-value',
                "Sent folder",
                "Main folder",
                "Icon color",
                'name="mailboxes__value_0_2"',
                'for="id_mailboxes__value_0_2"',
                'value="Incoming"',
            ]
        )

    def render_required_mapping(self, widget: MappingWidget) -> str:
        """Simulate the required attributes added by a bound MappingField."""
        return widget.render(
            "mailboxes",
            {"INBOX": {"label": "Incoming", "main_folder": True}},
            attrs={"id": "id_mailboxes", "required": True},
        )

    def optional_roles(self, value: Any) -> bool:
        """Require the mailbox label while allowing unchecked Sent and Main roles."""
        soup = BeautifulSoup(value, "html.parser")
        label = soup.select_one('[data-mailbox-label]')
        controls = soup.select('input[type="checkbox"], input[type="color"], [data-mailbox-color-value]')
        return bool(label and label.has_attr("required") and controls) and all(
            not control.has_attr("required") for control in controls
        )

    def get_test_scenarios(self) -> list[WidgetScenario[MappingWidget]]:
        """Prove MappingWidget supports fixed keys with compound setting values."""
        return [
            WidgetScenario(
                name="Mailbox mapping collection",
                constructor_kwargs={
                    "left": [("INBOX", "INBOX")],
                    "left_widget": forms.TextInput(attrs={"readonly": True}),
                    "right_widget": MailboxSettingsWidget(),
                    "allow_adding_groups": False,
                },
                post_construction=self.compact_layout,
                operations=[
                    WidgetOperation(
                        name="Extract nested inputs",
                        execute=self.extract,
                        result_validators=self.valid_values,
                    ),
                    WidgetOperation(
                        name="Required mapping keeps role and color inputs optional",
                        execute=self.render_required_mapping,
                        result_validators=self.optional_roles,
                    ),
                    WidgetOperation(
                        name="Render labelled settings",
                        execute=self.render_mapping,
                        result_validators=self.valid_html,
                    ),
                ],
            )
        ]
