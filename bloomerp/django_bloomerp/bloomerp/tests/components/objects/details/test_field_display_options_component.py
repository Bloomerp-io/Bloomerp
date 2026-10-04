"""Exercise field color configuration on real Todo layout owners."""

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.models import ApplicationField, Todo
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestFieldDisplayOptionsComponent(BloomerpComponentTestCase):
    """Verify restored mappings, valid saves, retired choices, and access checks."""

    view_name = "components_field_display_options"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create detail and create layouts containing the Todo status field."""
        super().setUp()
        self.status = ApplicationField.get_for_model(Todo).get(field="status")
        self.title_field = ApplicationField.get_for_model(Todo).get(field="title")
        layout = FieldLayout(
            rows=[
                LayoutRow(
                    columns=1,
                    items=[
                        LayoutItem(
                            id=self.status.pk,
                            config={
                                "label": "Progress",
                                "choice_colors": {
                                    "completed": "#00ff00",
                                    "retired": "#ff0000",
                                },
                                "unrelated": "preserved",
                            },
                        ),
                        LayoutItem(id=self.title_field.pk),
                    ],
                )
            ]
        ).model_dump(mode="json")
        self.preference = UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            name="Color settings",
            content_type=self.status.content_type,
            layout=layout,
        )
        self.form_owner = Form.objects.create(
            name="Todo create",
            content_type=self.status.content_type,
            layout=layout,
        )

    def _params(
        self, owner: UserObjectLayoutPreference | Form | None = None
    ) -> dict[str, Any]:
        """Supply the selected layout's identifiers for an editor request."""
        owner = owner or self.preference
        return {
            "layout_object_content_type_id": ContentType.objects.get_for_model(
                owner
            ).pk,
            "layout_object_id": str(owner.pk),
        }

    def _post_data(self, colors: str) -> dict[str, Any]:
        """Submit mappings through the mapping widget's JSON restoration path."""
        return {**self._params(), "label": "Updated progress", "choice_colors": colors}

    def _saved_colors(self, response: HttpResponse) -> bool:
        """Confirm valid settings persist without retaining retired mappings."""
        self.preference.refresh_from_db()
        config = self.preference.layout_obj.rows[0].items[0].config
        return config == {
            "label": "Updated progress",
            "choice_colors": {"completed": "#00ff00"},
            "unrelated": "preserved",
        }

    def _cleared_colors(self, response: HttpResponse) -> bool:
        """Confirm an empty mapping clears colors but preserves other settings."""
        self.preference.refresh_from_db()
        config = self.preference.layout_obj.rows[0].items[0].config
        return "choice_colors" not in config and config["unrelated"] == "preserved"

    def _unchanged(self, response: HttpResponse) -> bool:
        """Confirm invalid or unauthorized requests do not change persisted settings."""
        self.preference.refresh_from_db()
        return self.preference.layout_obj.rows[0].items[0].config["label"] == "Progress"

    def _remove_choices(self, scenario: RequestScenario) -> None:
        """Simulate a choice field whose refreshed metadata no longer has choices."""
        self.status.meta = {**self.status.meta, "choices": []}
        self.status.save(update_fields=["meta"])

    def _retire_completed(self, scenario: RequestScenario) -> None:
        """Simulate one removed choice without changing the underlying Todo model."""
        self.status.meta = {
            **self.status.meta,
            "choices": [
                choice
                for choice in self.status.meta["choices"]
                if choice[0] != "completed"
            ],
        }
        self.status.save(update_fields=["meta"])

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover the editor on both layout owners and graceful schema changes."""
        status_kwargs = {"application_field_id": self.status.pk}
        editor = [
            self.contains_text('name="choice_colors__value_'),
            self.contains_text("#00ff00"),
            self.contains_text("data-mapping-add"),
            self.contains_text("data-mapping-remove"),
            self.contains_text("Progress"),
            self.does_not_contain_text('value="retired"'),
        ]
        return [
            RequestScenario(
                name="Detail layout restores current colors",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                query_params=self._params(),
                expected=ExpectedResult(response_validators=editor),
            ),
            RequestScenario(
                name="Create layout restores current colors",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                query_params=self._params(self.form_owner),
                expected=ExpectedResult(response_validators=editor),
            ),
            RequestScenario(
                name="Saves mappings and drops retired choices",
                method="POST",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                data=self._post_data('{"completed":"#00ff00","retired":"#ff0000"}'),
                expected=ExpectedResult(response_validators=self._saved_colors),
            ),
            RequestScenario(
                name="Clears configured colors",
                method="POST",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                data=self._post_data("{}"),
                expected=ExpectedResult(response_validators=self._cleared_colors),
            ),
            RequestScenario(
                name="Invalid color displays errors without saving",
                method="POST",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                data=self._post_data('{"completed":"invalid"}'),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Enter a valid value"),
                        self._unchanged,
                    ]
                ),
            ),
            RequestScenario(
                name="Removed choice is omitted from the editor",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                query_params=self._params(),
                prepare=self._retire_completed,
                expected=ExpectedResult(
                    response_validators=[
                        self.does_not_contain_text('value="completed"'),
                        self.contains_text('name="choice_colors__value_'),
                    ]
                ),
            ),
            RequestScenario(
                name="Choices removed entirely leaves common options",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                query_params=self._params(),
                prepare=self._remove_choices,
                expected=ExpectedResult(
                    response_validators=[
                        self.does_not_contain_text('name="choice_colors'),
                        self.contains_text('name="label"'),
                    ]
                ),
            ),
            RequestScenario(
                name="Plain text field has no color editor",
                user=self.admin_user,
                view_kwargs={"application_field_id": self.title_field.pk},
                query_params=self._params(),
                expected=ExpectedResult(
                    response_validators=self.does_not_contain_text(
                        'name="choice_colors'
                    )
                ),
            ),
            RequestScenario(
                name="Normal user cannot change another user's layout",
                method="POST",
                user=self.normal_user,
                view_kwargs=status_kwargs,
                data=self._post_data('{"completed":"#00ff00"}'),
                expected=ExpectedResult(
                    status_code=403, response_validators=self._unchanged
                ),
            ),
            RequestScenario(
                name="Anonymous request is denied",
                view_kwargs=status_kwargs,
                query_params=self._params(),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Normal user without field grants cannot configure create form",
                user=self.normal_user,
                view_kwargs=status_kwargs,
                query_params=self._params(self.form_owner),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Missing layout is rejected",
                user=self.admin_user,
                view_kwargs=status_kwargs,
                expected=ExpectedResult(status_code=400),
            ),
        ]
