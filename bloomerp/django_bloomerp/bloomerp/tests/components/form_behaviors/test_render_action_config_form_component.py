"""Exercise action configuration fragments through the component scenario framework."""

import json
from typing import Any

from django.contrib.contenttypes.models import ContentType

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRenderActionConfigFormComponent(BloomerpComponentTestCase):
    """Verify target-dependent rendering, prefix isolation, and rejected requests."""

    view_name = "components_render_action_form"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create an owned layout and a real listener ApplicationField."""
        super().setUp()
        self.listener = ApplicationField.get_for_model(self.CustomerModel).get(
            field="first_name"
        )
        self.preference = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Action editor",
            content_type=self.listener.content_type,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=2,
                        items=[
                            LayoutItem(id="first_name"),
                            LayoutItem(id="last_name"),
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )

    def _params(self, **overrides: Any) -> dict[str, Any]:
        """Supply an authorized editor scope, listener, target, and unique prefix."""
        return {
            "layout_object_content_type_id": ContentType.objects.get_for_model(
                self.preference
            ).pk,
            "layout_object_id": str(self.preference.pk),
            "listener_field_id": self.listener.pk,
            "action_id": "set_value",
            "target_field": "last_name",
            "prefix": "behavior-one-action-one",
            **overrides,
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Describe real form rendering and errors without mocking factories or field lookup."""
        return [
            RequestScenario(
                name="Malformed layout identifiers produce a validation response rather than a server error",
                user=self.admin_user,
                query_params=self._params(layout_object_content_type_id="invalid"),
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Existing action and fields render prefixed configuration controls without a nested form",
                user=self.admin_user,
                query_params=self._params(config='{"value":"Restored text"}'),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('name="behavior-one-action-one-value"'),
                        self.contains_text('data-config-kind="value"'),
                        self.contains_text('type="text"'),
                        self.contains_text("Restored text"),
                        self.does_not_contain_text("<form"),
                    ]
                ),
            ),
            RequestScenario(
                name="An action requiring a target cannot render until a target is selected",
                user=self.admin_user,
                query_params=self._params(target_field=""),
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=[
                        self.json_key_equals(
                            "error", "['Select a target field first.']"
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="Unified fetch renders source, filter, selection, and ordering controls",
                user=self.admin_user,
                query_params=self._params(
                    action_id="fetch",
                    config=json.dumps({
                        "model": self.listener.content_type_id,
                        "fetch": "first",
                        "column": "first_name",
                    }),
                ),
                expected=ExpectedResult(response_validators=[
                    self.contains_text('name="behavior-one-action-one-model"'),
                    self.contains_text('name="behavior-one-action-one-filters"'),
                    self.contains_text('name="behavior-one-action-one-fetch"'),
                    self.contains_text('name="behavior-one-action-one-order_by"'),
                    self.contains_text('name="behavior-one-action-one-column"'),
                ]),
            ),
            RequestScenario(
                name="A targetless message action renders its validated message fields",
                user=self.admin_user,
                query_params=self._params(action_id="show_message", target_field=""),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('name="behavior-one-action-one-message"')
                    ]
                ),
            ),
            RequestScenario(
                name="An unknown action returns not found instead of constructing an arbitrary form",
                user=self.admin_user,
                query_params=self._params(action_id="unknown"),
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="A target outside the listener model is rejected",
                user=self.admin_user,
                query_params=self._params(target_field="nonexistent_field"),
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Configuration must be an object rather than an array",
                user=self.admin_user,
                query_params=self._params(config="[]"),
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Unknown configuration keys are rejected consistently with execution",
                user=self.admin_user,
                query_params=self._params(config='{"unexpected":true}'),
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="A missing prefix cannot introduce duplicate widget identifiers",
                user=self.admin_user,
                query_params=self._params(prefix=""),
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Another user cannot inspect this preference's action form",
                user=self.normal_user,
                query_params=self._params(),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Anonymous users must authenticate before rendering action configuration",
                query_params=self._params(),
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="The rendering endpoint does not accept POST mutations",
                method="POST",
                user=self.admin_user,
                data=self._params(),
                expected=ExpectedResult(status_code=405),
            ),
        ]
