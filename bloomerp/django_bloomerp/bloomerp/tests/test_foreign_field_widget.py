from django.http import QueryDict
from django.test import SimpleTestCase
from django.db import models
from unittest.mock import Mock, patch
import json

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class TestForeignFieldWidget(SimpleTestCase):
    def _staff_q_limit(self) -> models.Q:
        """Return a callable relation limit using Django's Q representation."""
        return models.Q(is_staff=True)

    def test_get_context_serializes_q_choice_limits(self) -> None:
        """Render Q limits as eligible IDs, including an empty matching set."""
        limits = [
            (models.Q(is_staff=True), [1, 2]),
            (models.Q(is_staff=True) | ~models.Q(is_active=True), [1, 2]),
            (self._staff_q_limit, [1, 2]),
            (models.Q(pk__in=[]), []),
        ]
        for limit, matching_ids in limits:
            with self.subTest(limit=limit):
                model_field = models.ForeignKey(
                    "auth.User", on_delete=models.CASCADE, limit_choices_to=limit,
                )
                source_field = Mock()
                source_field._get_model_field.return_value = model_field
                related_model = Mock()
                eligible_ids = related_model._default_manager.filter.return_value.values_list
                eligible_ids.return_value = matching_ids
                widget = ForeignFieldWidget(attrs={"source_field": source_field})

                with (
                    patch.object(widget, "get_related_content_type_id", return_value=1),
                    patch.object(widget, "get_related_model_class", return_value=related_model),
                ):
                    context = widget.get_context("assigned_to", None, {})

                self.assertEqual(json.loads(context["choices_filter_json"]), [{
                    "connector": "AND",
                    "conditions": [{
                        "field_path": "pk", "lookup_id": "values_in", "value": matching_ids,
                    }],
                }])
                related_model._default_manager.filter.assert_called_once_with(
                    model_field.get_limit_choices_to(),
                )
                eligible_ids.assert_called_once_with("pk", flat=True)

    def test_get_context_exposes_is_m2m_to_template(self):
        widget = ForeignFieldWidget(attrs={"is_m2m": True})

        context = widget.get_context("labels", None, {})

        self.assertTrue(context["widget"]["is_m2m"])

    def test_value_from_datadict_returns_all_m2m_values(self):
        widget = ForeignFieldWidget(attrs={"is_m2m": True})
        data = QueryDict("", mutable=True)
        data.update({"labels": "1"})
        data.appendlist("labels", "2")

        value = widget.value_from_datadict(data, {}, "labels")

        self.assertEqual(value, ["1", "2"])

    def test_value_from_datadict_returns_single_value_for_non_m2m(self):
        widget = ForeignFieldWidget()
        data = QueryDict("", mutable=True)
        data.update({"label": "1"})
        data.appendlist("label", "2")

        value = widget.value_from_datadict(data, {}, "label")

        self.assertEqual(value, "2")

    def test_value_from_datadict_allows_an_explicit_empty_single_value(self):
        """
        Use case: A user clears a foreign-key selection before submitting an object.
        Expected result: The empty hidden value is submitted instead of being treated as omitted.
        """

        # 1. Build the same two-value submission produced when a selected relation is cleared.
        widget = ForeignFieldWidget()
        data = QueryDict("label=1&label=", mutable=True)

        # 2. Read the submitted values from the custom widget.
        value = widget.value_from_datadict(data, {}, "label")

        # 3. Preserve the explicit empty value so partial updates can clear the relation.
        self.assertEqual(value, "")

    def test_get_context_includes_selected_urls_json(self):
        class DummyObject:
            pk = 7

            def __str__(self):
                return "Dummy"

            def get_absolute_url(self):
                return "/dummy/7/"

        widget = ForeignFieldWidget()

        context = widget.get_context("label", DummyObject(), {})

        self.assertEqual(json.loads(context["selected_urls_json"]), ["/dummy/7/"])
