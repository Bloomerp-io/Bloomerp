from django import forms
from django.db.models import Q

from bloomerp.lookups.builtins.ends_with import ENDS_WITH
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL, FilterFieldContext
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestEndsWithLookup(BloomerpLookupTestCase):
    lookup = ENDS_WITH

    def test_default_form_factory_returns_an_optional_char_field(self) -> None:
        form_factory = self.get_lookup().get_form_factory()
        self.assertIsNotNone(form_factory)

        application_field = self.get_application_field("first_name")
        form_field = form_factory(FilterFieldContext(
            field_type=application_field.get_field_type(),
            application_field=application_field,
        ))

        self.assertIsInstance(form_field, forms.CharField)
        self.assertFalse(form_field.required)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="canonical expression",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="ends_with",
                value="son",
                expected_lookup=CompiledLookup(
                    predicate=Q(first_name__endswith="son")
                ),
                expected_sql=CompiledSQL(
                    clause="first_name LIKE %s",
                    parameters=("%son",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="Johnson", expected=True),
                    PythonEvaluation(actual="Johnson Jr.", expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            ),
            LookupScenario(
                name="Django expression alias",
                application_field=lambda: self.get_application_field("last_name"),
                field_path="last_name",
                expression="endswith",
                value="er",
                expected_lookup=CompiledLookup(
                    predicate=Q(last_name__endswith="er")
                ),
            ),
        ]
