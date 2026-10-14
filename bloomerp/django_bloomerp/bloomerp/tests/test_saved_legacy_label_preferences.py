"""Saved UI preferences remain usable after the legacy label relations retire."""

from collections.abc import Callable
from copy import deepcopy
from importlib import import_module
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import HttpResponse

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.communication.label import Label
from bloomerp.models.communication.object_label import ObjectLabel
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests import base
from bloomerp.tests.base import (
    ExpectedResult,
    ModelRequestScenario,
    RequestScenario,
)


class LegacyLabelPreferenceFixtures:
    """Create old persisted metadata without restoring the retired Django fields."""

    auto_create_customers = False

    def prepare_legacy_fields(
        self, model: type[Model]
    ) -> tuple[ContentType, ApplicationField, int]:
        """Create the former metadata needed to persist an old preference accurately."""
        content_type = ContentType.objects.get_for_model(model)
        title_name = "title" if model is Todo else "name"
        title_field = ApplicationField.get_for_model(model).get(field=title_name)
        legacy_field = ApplicationField.objects.create(
            content_type=content_type,
            field="labels",
            field_type="ManyToManyField",
        )
        return content_type, title_field, legacy_field.pk


class TestSavedLegacyLabelDataviews(
    LegacyLabelPreferenceFixtures, base.BloomerpComponentTestCase
):
    """Exercise saved table and Kanban preferences through the real component."""

    view_name = "components_dataview"

    def prepare_dataview(
        self,
        model: type[Model],
        view_type: str,
        option_reference: str,
    ) -> Callable[[RequestScenario], None]:
        """Build an isolated saved preference containing a retired field reference."""

        def prepare(scenario: RequestScenario) -> None:
            """Persist the old field IDs and options before the request is made."""
            content_type, title_field, legacy_id = self.prepare_legacy_fields(model)
            model.objects.create(
                **{title_field.field: "Surviving project management record"}
            )
            field_reference: str | int = (
                legacy_id if option_reference == "id" else "labels"
            )
            options: dict[str, Any] = {
                "page_size": 10,
                "sort_field": field_reference,
                "sort_direction": "desc",
            }
            if view_type == "kanban":
                options.update(
                    {
                        "group_by_field": field_reference,
                        "custom_groupings": {"Saved lane": ["old-label"]},
                        "custom_group_order": ["Saved lane"],
                        "show_unmapped_lanes": False,
                        "lane_colouring": {"Saved lane": "#336699"},
                    }
                )
            self.saved_options = {view_type: options}
            self.saved_preference = UserListViewPreference.objects.create(
                user=scenario.user,
                content_type=content_type,
                selected=True,
                view_type=view_type,
                display_fields={view_type: [legacy_id, title_field.pk]},
                options=self.saved_options,
            )
            # Both migration 0093 and the regular metadata sync retire this row.
            ApplicationField.objects.filter(pk=legacy_id).delete()
            self.expected_title_field = title_field
            self.legacy_field_id = legacy_id
            scenario.view_kwargs = {"content_type_id": content_type.pk}

        return prepare

    def dataview_keeps_surviving_fields(self, response: HttpResponse) -> bool:
        """Check that rendering drops retired columns and leaves saved options intact."""
        self.saved_preference.refresh_from_db()
        fields = response.context["fields"]
        return (
            [field.pk for field in fields.visible_fields]
            == [self.expected_title_field.pk]
            and all(field.field != "labels" for field, _ in fields.accessible_fields)
            and self.saved_preference.options == self.saved_options
            and self.saved_preference.get_visible_field_ids()
            == [self.expected_title_field.pk]
            and (
                self.saved_preference.view_type != "table"
                or response.context["current_sort_field"] == ""
            )
            and (
                self.saved_preference.view_type != "kanban"
                or response.context["group_by_field"] is None
            )
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover old numeric IDs and newer field names for both retired relations."""
        scenarios = [
            RequestScenario(
                name=(
                    f"{model.__name__} {view_type} with {reference} options "
                    "after retired field metadata cleanup"
                ),
                user=self.admin_user,
                prepare=self.prepare_dataview(model, view_type, reference),
                expected=ExpectedResult(
                    response_validators=self.dataview_keeps_surviving_fields
                ),
            )
            for model in (Todo, Initiative)
            for view_type in ("table", "kanban")
            for reference in ("id", "name")
        ]
        scenarios.extend(
            RequestScenario(
                name=f"{model.__name__} renders a migrated {lookup} {shape} saved filter",
                user=self.admin_user,
                prepare=self.prepare_saved_filter(model, lookup, shape),
                expected=ExpectedResult(
                    response_validators=self.saved_filter_keeps_exact_membership
                ),
            )
            for model in (Todo, Initiative)
            for lookup, shape in (
                ("equals", "scalar"),
                ("equals", "singleton"),
                ("not_equals", "scalar"),
                ("not_equals", "singleton"),
                ("values_in", "multiple"),
                ("values_in", "empty"),
            )
        )
        return scenarios

    def prepare_saved_filter(
        self, model: type[Model], lookup: str, shape: str
    ) -> Callable[[RequestScenario], None]:
        """Translate a real saved preset and verify its surviving HTTP behavior."""

        def prepare(scenario: RequestScenario) -> None:
            """Preserve mixed Boolean groups while mapping former UUID membership."""
            content_type = ContentType.objects.get_for_model(model)
            title_name = "title" if model is Todo else "name"
            title_field = ApplicationField.get_for_model(model).get(field=title_name)
            primary = Label.objects.create(name="Primary migrated label")
            secondary = Label.objects.create(name="Secondary migrated label")
            first_id = UUID("076e0efc-9af6-4d81-aed5-b0fc9809abe2")
            duplicate_id = UUID("58f2daf5-630b-40eb-8d29-e50f5a9b8c53")
            second_id = UUID("2350decd-f27f-4b0b-9adc-53112c35d5b1")
            label_ids = {
                first_id: primary.pk,
                duplicate_id: primary.pk,
                second_id: secondary.pk,
            }
            input_values: dict[str, Any] = {
                "scalar": str(first_id),
                "singleton": [str(first_id)],
                "multiple": [str(first_id), str(duplicate_id), str(second_id)],
                "empty": [],
            }
            records: dict[str, Model] = {}
            for title, labels in (
                ("Primary only", [primary]),
                ("Secondary only", [secondary]),
                ("Both labels", [primary, secondary]),
                ("No labels", []),
                ("Always included", []),
                ("Excluded status", [primary, secondary]),
            ):
                record = model.objects.create(
                    **{
                        title_name: title,
                        "status": "in_progress"
                        if title == "Excluded status"
                        else "backlog",
                    }
                )
                records[title] = record
                for label in labels:
                    ObjectLabel.objects.create(
                        content_type=content_type,
                        object_id=str(record.pk),
                        label=label,
                    )
            preference = UserListViewPreference.objects.create(
                user=scenario.user,
                content_type=content_type,
                selected=True,
                display_fields={"table": [title_field.pk]},
            )
            old_groups = [
                {
                    "connector": "OR",
                    "conditions": [
                        {
                            "field_path": "labels",
                            "lookup_id": lookup,
                            "value": input_values[shape],
                        },
                        {
                            "field_path": title_name,
                            "lookup_id": "equals",
                            "value": "Always included",
                        },
                    ],
                },
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "status",
                            "lookup_id": "equals",
                            "value": "backlog",
                        }
                    ],
                },
            ]
            self.saved_filter = SavedFilter.objects.create(
                name="Saved legacy label filter",
                scope="model",
                identifier=str(content_type.pk),
                filters=old_groups,
            )
            preference.add_default_filter(self.saved_filter)
            migration = import_module("bloomerp.migrations.0093_migrate_todo_labels")
            translated = migration.translate_label_condition(
                old_groups[0]["conditions"][0], label_ids
            )
            self.expected_saved_groups = deepcopy(old_groups)
            self.expected_saved_groups[0]["conditions"][0] = translated
            SavedFilter.objects.filter(pk=self.saved_filter.pk).update(
                filters=self.expected_saved_groups
            )
            self.assertEqual(old_groups[0]["conditions"][0]["field_path"], "labels")
            expected_titles = {"Always included"}
            if lookup == "equals":
                expected_titles.update({"Primary only", "Both labels"})
            elif lookup == "not_equals":
                expected_titles.update({"Secondary only", "No labels"})
            elif shape == "multiple":
                expected_titles.update(
                    {"Primary only", "Secondary only", "Both labels"}
                )
            self.expected_filter_record_ids = {
                records[title].pk for title in expected_titles
            }
            scenario.view_kwargs = {"content_type_id": content_type.pk}

        return prepare

    def saved_filter_keeps_exact_membership(self, response: HttpResponse) -> bool:
        """Require correct rows and unmodified AND/OR structure after migration."""
        self.saved_filter.refresh_from_db()
        actual_ids = {record.pk for record in response.context["page_obj"]}
        return (
            actual_ids == self.expected_filter_record_ids
            and self.saved_filter.filters == self.expected_saved_groups
        )


class LegacyLabelObjectFormScenarios(LegacyLabelPreferenceFixtures):
    """Share saved-layout fixtures for the ordinary create and detail routes."""

    def prepare_layout(
        self, *, only_legacy_field: bool
    ) -> Callable[[ModelRequestScenario], None]:
        """Return setup for a partial or fully retired saved object form layout."""

        def prepare(scenario: ModelRequestScenario) -> None:
            """Save a former labels item alongside an optional surviving title."""
            content_type, title_field, legacy_id = self.prepare_legacy_fields(
                scenario.model
            )
            items = [LayoutItem(id=legacy_id)]
            if not only_legacy_field:
                items.append(LayoutItem(id=title_field.pk))
            self.saved_layout = FieldLayout(
                rows=[LayoutRow(columns=2, items=items)]
            ).model_dump(mode="json")
            self.saved_preference = UserObjectLayoutPreference.objects.create(
                user=scenario.user,
                content_type=content_type,
                selected=True,
                layout=self.saved_layout,
            )
            # Both migration 0093 and the regular metadata sync retire this row.
            ApplicationField.objects.filter(pk=legacy_id).delete()
            self.expected_title_field = title_field
            self.legacy_field_id = legacy_id
            if self.view_name == "overview":
                instance = scenario.model.objects.create(
                    **{title_field.field: "Surviving object form record"}
                )
                scenario.view_kwargs = {"pk": instance.pk}

        return prepare

    def layout_keeps_surviving_fields(self, response: HttpResponse) -> bool:
        """Require a usable form without rewriting the user's saved layout JSON."""
        self.saved_preference.refresh_from_db()
        item_ids = {
            str(item.id)
            for row in response.context["layout"].rows
            for item in row.items
        }
        return (
            str(self.legacy_field_id) not in item_ids
            and str(self.expected_title_field.pk) in item_ids
            and self.expected_title_field.field in response.context["form"].fields
            and "labels" not in response.context["form"].fields
            and self.saved_preference.layout == self.saved_layout
        )

    def get_test_scenarios(self) -> list[ModelRequestScenario]:
        """Exercise partial layouts and all-retired fallback layouts for each model."""
        return [
            ModelRequestScenario(
                name=(
                    f"{model.__name__} {self.view_name} with "
                    f"{'only retired' if only_legacy else 'mixed'} saved items "
                    "after retired field metadata cleanup"
                ),
                model=model,
                user=self.admin_user,
                headers={"HX-Request": "true"},
                prepare=self.prepare_layout(only_legacy_field=only_legacy),
                expected=ExpectedResult(
                    response_validators=self.layout_keeps_surviving_fields
                ),
            )
            for model in (Todo, Initiative)
            for only_legacy in (False, True)
        ]


class TestSavedLegacyLabelCreateForms(
    LegacyLabelObjectFormScenarios, base.BloomerpModelViewTestCase
):
    """Saved object layouts must still open the create form after label retirement."""

    view_name = "add"


class TestSavedLegacyLabelDetailForms(
    LegacyLabelObjectFormScenarios, base.BloomerpDetailViewTestCase
):
    """Saved object layouts must still open the existing object's detail form."""

    view_name = "overview"
