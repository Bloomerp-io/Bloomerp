"""Tests for fetching a top-level form value from an authorized record."""

from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.fetch_value import FETCH_VALUE
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorMessage,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.utils import clean_action_config
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase


class TestFetchValueAction(BloomerpBehaviorActionTestCase):
    """Verify matching, deterministic selection, no-match, and denied lookups."""

    action = FETCH_VALUE

    def _config(
        self,
        *,
        filters: list[dict[str, Any]] | None = None,
        strategy: str = "first",
    ) -> dict[str, Any]:
        """Build portable lookup configuration for the customer fixture."""
        return {
            "fetch_from": ContentType.objects.get_for_model(self.CustomerModel).pk,
            "fetch_field": "last_name",
            "filters": filters or [],
            "fetch_strategy": strategy,
        }

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Cover object placeholders, first/last ordering, and unmatched filters."""
        listener = self.get_application_field("first_name")
        target = self.get_application_field("last_name")
        first = self.CustomerModel.objects.order_by("pk").first()
        last = self.CustomerModel.objects.order_by("-pk").first()
        assert first is not None and last is not None
        matching = [
            {
                "connector": "AND",
                "conditions": [
                    {
                        "field_path": "first_name",
                        "lookup_id": "equals",
                        "value": "{{ object.first_name }}",
                    }
                ],
            }
        ]
        missing = [
            {
                "connector": "AND",
                "conditions": [
                    {
                        "field_path": "first_name",
                        "lookup_id": "equals",
                        "value": "No such customer",
                    }
                ],
            }
        ]
        return [
            BehaviorActionScenario(
                name="An object placeholder selects the matching source record",
                context=BehaviorContext(
                    values={"first_name": first.first_name, "last_name": ""},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                listener=listener,
                target=target,
                config=self._config(filters=matching),
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="last_name", value=first.last_name),)
                ),
            ),
            BehaviorActionScenario(
                name="Last uses deterministic descending primary-key order",
                context=BehaviorContext(
                    values={"first_name": "Draft", "last_name": ""},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                listener=listener,
                target=target,
                config=self._config(strategy="last"),
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="last_name", value=last.last_name),)
                ),
            ),
            BehaviorActionScenario(
                name="No matching source record leaves the draft unchanged",
                context=BehaviorContext(
                    values={"first_name": "Draft", "last_name": "Existing"},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                listener=listener,
                target=target,
                config=self._config(filters=missing),
                expected_result=BehaviorResult(),
            ),
        ]

    def test_denied_source_field_returns_permission_message(self) -> None:
        """Use the shared denied-result factory when source data is inaccessible."""
        listener = self.get_application_field("first_name")
        target = self.get_application_field("last_name")
        context = BehaviorContext(
            values={"first_name": "Draft", "last_name": ""},
            listener_field="first_name",
            target_field="last_name",
        )
        with patch.object(
            UserPolicyManager, "has_field_permission", return_value=False
        ):
            result = self.action.run(
                context,
                self._config(),
                listener=listener,
                target=target,
                user=self.normal_user,
            )
        self.assertEqual(
            result,
            BehaviorResult(
                messages=(
                    BehaviorMessage(
                        type="danger",
                        message="Permission denied: you cannot read the configured lookup data",
                    ),
                )
            ),
        )

    def test_definition_explains_lookup_and_group(self) -> None:
        """Expose a clear label, description, and editor group."""
        self.assertEqual(self.action.group, "Data lookup")
        self.assertIn("record", self.action.label.lower())
        self.assertIn("filters", self.action.description.lower())

    def test_collection_fields_are_excluded_from_targets(self) -> None:
        """Offer only values that the action can fetch and serialize as one value."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        many_to_many = ApplicationField.objects.create(
            content_type=content_type,
            field="unsupported_many_to_many",
            field_type=FIELD_TYPE_REGISTRY.MANY_TO_MANY_FIELD.id,
        )
        one_to_many = ApplicationField.objects.create(
            content_type=content_type,
            field="unsupported_one_to_many",
            field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id,
        )
        last_name = self.get_application_field("last_name")
        candidates = ApplicationField.objects.filter(
            pk__in=[many_to_many.pk, one_to_many.pk, last_name.pk]
        )

        eligible = self.action.get_target_fields(candidates, None)

        self.assertEqual(list(eligible.values_list("field", flat=True)), ["last_name"])

    def test_object_placeholders_declare_executor_dependencies(self) -> None:
        """Expose referenced fields so the executor loads their supplied draft values."""
        target = self.get_application_field("last_name")
        cleaned = clean_action_config(
            self.action,
            self.get_application_field("age"),
            target,
            self._config(
                filters=[
                    {
                        "connector": "AND",
                        "conditions": [
                            {
                                "field_path": "first_name",
                                "lookup_id": "equals",
                                "value": "{{ object.first_name }}",
                            }
                        ],
                    }
                ]
            ),
        )
        references = cleaned["value_references"]
        self.assertEqual(len(references), 1)
        self.assertIsInstance(references[0], BehaviorFieldReference)
        self.assertEqual(references[0].field.field, "first_name")
