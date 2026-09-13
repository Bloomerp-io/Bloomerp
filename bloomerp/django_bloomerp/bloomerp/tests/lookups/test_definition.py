from unittest import TestCase
from unittest.mock import Mock
from types import SimpleNamespace

from django import forms

from django.db.models import Q

from bloomerp.lookups.definition import (
    BoundLookup,
    CompiledLookup,
    FilterFieldContext,
    LookupDefinition,
    default_q_factory,
)


class TestLookupExecutionContract(TestCase):
    def test_nested_lookup_only_discovers_fields(self):
        discover = lambda model, path: []
        lookup = LookupDefinition(
            id="nested", label="Nested", expressions=(), nested=True,
            nested_fields_factory=discover,
        )
        bound = BoundLookup.normalize(lookup)
        self.assertIs(lookup.nested_fields_factory, discover)
        self.assertIsNone(bound.get_q_factory())
        self.assertIsNone(bound.get_sql_factory())
        self.assertIsNone(bound.get_python_evaluator())

    def test_nested_lookup_rejects_execution_factories(self):
        for name in ("q_factory", "sql_factory", "python_evaluator"):
            with self.subTest(factory=name), self.assertRaises(ValueError):
                LookupDefinition(
                    id="nested", label="Nested", expressions=(), nested=True,
                    **{name: lambda *args: None},
                )

    def test_bound_nested_lookup_rejects_execution_overrides(self):
        lookup = LookupDefinition(
            id="nested", label="Nested", expressions=(), nested=True,
        )
        for name in ("q_factory", "sql_factory", "python_evaluator"):
            with self.subTest(factory=name), self.assertRaises(ValueError):
                BoundLookup(lookup=lookup, **{name: lambda *args: None})

    def test_terminal_lookup_keeps_default_q_compilation(self):
        lookup = LookupDefinition(id="exact", label="Equals", expressions=("exact",))
        factory = BoundLookup.normalize(lookup).get_q_factory()
        self.assertIs(factory, default_q_factory)
        self.assertEqual(
            factory(None, "customer__name", "exact", "Bloom"),
            CompiledLookup(predicate=Q(customer__name__exact="Bloom")),
        )

    def test_terminal_lookup_preserves_custom_factory_and_override(self):
        custom = lambda *args: CompiledLookup(predicate=Q(name="custom"))
        override = lambda *args: CompiledLookup(predicate=Q(name="override"))
        lookup = LookupDefinition(
            id="exact", label="Equals", expressions=("exact",), q_factory=custom,
        )
        self.assertIs(BoundLookup.normalize(lookup).get_q_factory(), custom)
        self.assertIs(BoundLookup(lookup=lookup, q_factory=override).get_q_factory(), override)


class TestFilterFieldContext(TestCase):
    def test_model_editor_is_built_once(self):
        editor = forms.IntegerField(min_value=2)
        application_field = Mock()
        application_field.get_form_field.return_value = editor
        context = FilterFieldContext(
            field_type=SimpleNamespace(form_factory=None, widget_factory=None), application_field=application_field,
        )
        self.assertIs(context.get_form_field(), editor)
        application_field.get_form_field.assert_called_once_with()

    def test_analytics_editor_uses_factory_and_is_fresh(self):
        field_type = SimpleNamespace(
            form_factory=lambda context, default: forms.IntegerField(min_value=2),
            widget_factory=None,
        )
        context = FilterFieldContext(field_type=field_type)
        first = context.get_form_field()
        second = context.get_form_field()
        self.assertIsInstance(first, forms.IntegerField)
        self.assertEqual(first.clean("3"), 3)
        self.assertEqual(first.min_value, 2)
        self.assertIsNot(first, second)
        first.widget.attrs["data-test"] = "changed"
        self.assertNotIn("data-test", second.widget.attrs)

    def test_choices_do_not_require_an_application_field(self):
        context = FilterFieldContext(
            field_type=SimpleNamespace(
                form_factory=lambda context, default: forms.ChoiceField(choices=(("retail", "Retail"),)),
                widget_factory=None,
            ),
        )
        editor = context.get_form_field()
        self.assertIsInstance(editor, forms.ChoiceField)
        self.assertEqual(editor.clean("retail"), "retail")
        self.assertFalse(editor.valid_value("unknown"))

    def test_missing_model_editor_falls_back_to_text(self):
        application_field = Mock()
        application_field.get_form_field.return_value = None
        context = FilterFieldContext(
            field_type=SimpleNamespace(form_factory=None, widget_factory=None), application_field=application_field,
        )
        self.assertIsInstance(context.get_form_field(), forms.CharField)
