from django.http import QueryDict
from django.test import SimpleTestCase
import json

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class TestForeignFieldWidget(SimpleTestCase):
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
