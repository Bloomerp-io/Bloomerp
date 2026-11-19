from django.db.models import Q

from bloomerp.lookups.builtins.contains import CONTAINS, contains_form_factory
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    FilterFieldContext,
    SQLLookupContext,
)
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestContainsLookup(BloomerpLookupTestCase):
    lookup = CONTAINS

    def get_test_scenarios(self) -> list[LookupScenario]:
        """Check case-insensitive matching and literal SQL wildcard escaping."""
        return [
            LookupScenario(
                name="case-insensitive text containment",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="contains",
                value="AV",
                expected_lookup=CompiledLookup(
                    predicate=Q(first_name__icontains="AV")
                ),
                expected_sql=CompiledSQL(
                    clause="first_name ILIKE %s ESCAPE '!'",
                    parameters=("%AV%",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="David", expected=True),
                    PythonEvaluation(actual="Sarah", expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            ),
            LookupScenario(
                name="case-insensitive containment outside PostgreSQL",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="icontains",
                value="av",
                expected_lookup=CompiledLookup(
                    predicate=Q(first_name__icontains="av")
                ),
                expected_sql=CompiledSQL(
                    clause="LOWER(first_name) LIKE LOWER(%s) ESCAPE '!'",
                    parameters=("%av%",),
                ),
                sql_context=SQLLookupContext(
                    field_path="first_name",
                    dialect="sqlite",
                ),
            ),
            LookupScenario(
                name="percent underscore and escape characters are literal",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name", expression="contains", value="O'Reilly%_!",
                expected_lookup=CompiledLookup(predicate=Q(first_name__icontains="O'Reilly%_!")),
                expected_sql=CompiledSQL(
                    clause="first_name ILIKE %s ESCAPE '!'",
                    parameters=("%O'Reilly!%!_!!%",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="O'Reilly%_! example", expected=True),
                    PythonEvaluation(actual="O'ReillyXX!", expected=False),
                ],
            ),
        ]

    def test_contains_input_uses_full_width_input_styles(self) -> None:
        """Use case: The filter editor renders a Contains text input.
        Expected result: Its markup includes both standard input classes.
        """
        # 1. Build the actual lookup form field from its application field context.
        application_field = self.get_application_field("first_name")
        field = contains_form_factory(FilterFieldContext(
            field_type=application_field.get_field_type(), application_field=application_field,
        ))
        # 2. Styling is a widget contract outside compiled lookup scenarios.
        self.assertEqual(set(field.widget.attrs["class"].split()), {"input", "w-full"})
