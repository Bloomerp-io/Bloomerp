"""Exercise saved form behaviors through the routed request-scenario framework."""

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.form_behaviors.builtins import (
    SET_FIELD_INTERACTION,
    SET_FIELD_VISIBILITY,
    SET_VALUE,
)
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    FormBehavior,
)
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestExecuteComponent(BloomerpComponentTestCase):
    """Verify real HTTP execution of saved behaviors, without mocking actions."""

    view_name = "components_form_behavior_execute"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create a persisted customer whose values must survive every preview."""
        super().setUp()
        self.customer = self.CustomerModel.objects.create(
            first_name="Original",
            last_name="Customer",
            age=18,
        )

    def _set_last_name(self) -> BehaviorAction:
        """Build a set-value action using a native JSON string configuration."""
        return BehaviorAction(
            action=SET_VALUE,
            target_field="last_name",
            config={"value": "Suggested surname"},
        )

    def _preference(
        self,
        name: str,
        behaviors: list[FormBehavior],
        *,
        owned_by_admin: bool = True,
    ) -> UserObjectLayoutPreference:
        """Store declarations on a listener field in an explicitly owned layout."""
        layout = FieldLayout(
            rows=[
                LayoutRow(
                    columns=3,
                    items=[
                        LayoutItem(
                            id="first_name",
                            config={
                                "behaviors": BehaviorConfig(
                                    behaviors=behaviors
                                ).to_storage(),
                            },
                        ),
                        LayoutItem(id="last_name"),
                        LayoutItem(id="age"),
                    ],
                )
            ]
        )
        return UserObjectLayoutPreference.objects.create(
            name=name,
            user=self.admin_user if owned_by_admin else self.normal_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            layout=layout.model_dump(mode="json"),
        )

    def _payload(self, preference: UserObjectLayoutPreference) -> dict[str, Any]:
        """Supply draft values and a revision that the response must echo."""
        return {
            "preference_id": str(preference.pk),
            "object_id": str(self.customer.pk),
            "listener_field": "first_name",
            "event": "change",
            "revision": 12,
            "values": {"first_name": "Draft", "last_name": "Customer", "age": 18},
        }

    def _customer_is_unchanged(self, response: HttpResponse) -> bool:
        """Verify successful and failed evaluations both leave persisted values intact."""
        self.customer.refresh_from_db()
        return (
            self.customer.first_name,
            self.customer.last_name,
            self.customer.age,
        ) == (
            "Original",
            "Customer",
            18,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Describe updates, event filtering, failed batches, and access boundaries."""
        success = self._preference(
            "Successful draft updates",
            [
                FormBehavior(
                    id="suggest-and-hide",
                    actions=[
                        self._set_last_name(),
                        BehaviorAction(
                            action=SET_FIELD_VISIBILITY,
                            target_field="last_name",
                            config={"visibility": "hidden"},
                        ),
                    ],
                )
            ],
        )
        disabled_state = self._preference(
            "Explicit disabled state",
            [FormBehavior(
                id="disable-last-name",
                actions=[BehaviorAction(
                    action=SET_FIELD_INTERACTION,
                    target_field="last_name",
                    config={"interaction": "disabled"},
                )],
            )],
        )
        enabled_state = self._preference(
            "Explicit enabled state",
            [FormBehavior(
                id="enable-last-name",
                actions=[BehaviorAction(
                    action=SET_FIELD_INTERACTION,
                    target_field="last_name",
                    config={"interaction": "enabled"},
                )],
            )],
        )
        skipped = self._preference(
            "Inactive and unmatched behaviors",
            [
                FormBehavior(
                    id="disabled", enabled=False, actions=[self._set_last_name()]
                ),
                FormBehavior(
                    id="initial-only",
                    events=["initial"],
                    actions=[self._set_last_name()],
                ),
                FormBehavior(
                    id="condition-not-met",
                    conditions=[
                        Filter(
                            connector="AND",
                            conditions=[
                                FilterCondition(
                                    field_path="age",
                                    lookup_id="equals",
                                    value=99,
                                )
                            ],
                        )
                    ],
                    actions=[self._set_last_name()],
                ),
            ],
        )
        failed = self._preference(
            "Failure after a proposed update",
            [
                FormBehavior(
                    id="second-action-unknown",
                    actions=[
                        self._set_last_name(),
                        BehaviorAction(
                            action="unregistered_test_action", target_field="last_name"
                        ),
                    ],
                )
            ],
        )
        missing_target = self._preference(
            "Missing required target",
            [
                FormBehavior(
                    id="target-not-configured",
                    actions=[
                        BehaviorAction(action=SET_VALUE, config={"value": "Ignored"})
                    ],
                )
            ],
        )
        other_owner = self._preference(
            "Another user's layout", [], owned_by_admin=False
        )
        shared_owner = self._preference(
            "Shared behavior layout",
            [FormBehavior(id="shared-suggestion", actions=[self._set_last_name()])],
            owned_by_admin=False,
        )
        shared_owner.shared_with_users.add(self.admin_user)
        PreferenceManager(self.admin_user).select(shared_owner)
        shared_payload = self._payload(shared_owner)
        shared_payload.pop("object_id")
        normal_owner = self._preference(
            "No model permissions",
            [FormBehavior(
                id="draft-only-suggestion",
                actions=[self._set_last_name()],
            )],
            owned_by_admin=False,
        )
        normal_payload = self._payload(normal_owner)
        normal_payload.pop("object_id")
        form_owner = Form.objects.create(
            name="Behavior form",
            content_type=success.content_type,
            layout=success.layout,
        )
        form_payload = self._payload(success)
        form_payload.pop("preference_id")
        form_payload["form_id"] = str(form_owner.pk)
        public_form_payload = {**form_payload}
        public_form_payload.pop("object_id")
        authenticated_form_owner = Form.objects.create(
            name="Authenticated behavior form",
            content_type=success.content_type,
            layout=success.layout,
            requires_authentication=True,
        )
        authenticated_form_payload = {
            **public_form_payload,
            "form_id": str(authenticated_form_owner.pk),
        }
        invalid_payload = self._payload(success)
        invalid_payload["revision"] = -1

        return [
            RequestScenario(
                name="A UUID-backed create form does not evaluate an unsaved object",
                view_name="todos_add",
                user=self.admin_user,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('data-behavior-url="'),
                        self.does_not_contain_text('data-behavior-object-id="'),
                    ]
                ),
            ),
            RequestScenario(
                name="A Form-owned layout uses the same execution and response contract as a preference",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=form_payload,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals(
                            "values",
                            [{"field": "last_name", "value": "Suggested surname"}],
                        ),
                        self._customer_is_unchanged,
                    ]
                ),
            ),
            RequestScenario(
                name="An anonymous public Form submission can evaluate its saved behaviors",
                method="POST",
                content_type="application/json",
                data=public_form_payload,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals(
                            "values",
                            [{"field": "last_name", "value": "Suggested surname"}],
                        ),
                        self._customer_is_unchanged,
                    ]
                ),
            ),
            RequestScenario(
                name="An anonymous respondent cannot evaluate an authentication-required Form",
                method="POST",
                content_type="application/json",
                data=authenticated_form_payload,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="An authenticated respondent can evaluate an authentication-required Form",
                method="POST",
                user=self.normal_user,
                content_type="application/json",
                data=authenticated_form_payload,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals(
                            "values",
                            [{"field": "last_name", "value": "Suggested surname"}],
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="Negative: Supplying both form and preference identities is rejected as ambiguous",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={**self._payload(success), "form_id": str(form_owner.pk)},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Changing a listener returns value and visibility updates without saving the customer",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(success),
                expected=ExpectedResult(
                    response_validators=[
                        self.json_exact(
                            {
                                "revision": 12,
                                "values": [
                                    {"field": "last_name", "value": "Suggested surname"}
                                ],
                                "states": [{
                                    "field": "last_name",
                                    "visible": False,
                                    "disabled": None,
                                }],
                                "messages": [],
                            }
                        ),
                        self._customer_is_unchanged,
                    ]
                ),
            ),
            RequestScenario(
                name="Explicit disabled state is serialized with independent visibility",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(disabled_state),
                expected=ExpectedResult(response_validators=[
                    self.json_key_equals("states", [{
                        "field": "last_name",
                        "visible": None,
                        "disabled": True,
                    }]),
                    self._customer_is_unchanged,
                ]),
            ),
            RequestScenario(
                name="Explicit enabled state is serialized with independent visibility",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(enabled_state),
                expected=ExpectedResult(response_validators=[
                    self.json_key_equals("states", [{
                        "field": "last_name",
                        "visible": None,
                        "disabled": False,
                    }]),
                    self._customer_is_unchanged,
                ]),
            ),
            RequestScenario(
                name="Disabled behaviors, initial-only events, and false conditions produce no changes",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(skipped),
                expected=ExpectedResult(
                    response_validators=[
                        self.json_exact(
                            {"revision": 12, "values": [], "states": [], "messages": []}
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="An unknown second action rejects the entire batch instead of returning the first update",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(failed),
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=[
                        self.json_exact(
                            {
                                "error": "Behavior evaluation failed.",
                                "detail": "['Unknown action: unregistered_test_action.']",
                            }
                        ),
                        self._customer_is_unchanged,
                    ],
                ),
            ),
            RequestScenario(
                name="Set-value execution rejects a saved action without its required target field",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(missing_target),
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=[
                        self.json_key_equals(
                            "detail", "['Action requires a target field.']"
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="A negative draft revision is rejected before evaluating behaviors",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=invalid_payload,
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=[
                        self.json_exact(
                            {"error": "Invalid behavior execution request."}
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="A selected shared preference can execute its owner's live behaviors",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=shared_payload,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals(
                            "values",
                            [{"field": "last_name", "value": "Suggested surname"}],
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="Even an administrator cannot execute another user's saved preference",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data=self._payload(other_owner),
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="A preference create draft does not require model write permission",
                method="POST",
                user=self.normal_user,
                content_type="application/json",
                data=normal_payload,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals(
                            "values",
                            [{
                                "field": "last_name",
                                "value": "Suggested surname",
                            }],
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="Anonymous callers cannot evaluate a saved user preference",
                method="POST",
                content_type="application/json",
                data=self._payload(success),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Authenticated GET requests cannot evaluate behaviors",
                method="GET",
                user=self.admin_user,
                expected=ExpectedResult(status_code=405),
            ),
        ]
