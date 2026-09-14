from django.db.models import Q

from bloomerp.lookups.builtins.is_null import IS_NULL
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestIsNullLookup(BloomerpLookupTestCase):
    lookup = IS_NULL

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="truthy serialized value",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="is_null",
                value="true",
                sql_value=True,
                expected_lookup=CompiledLookup(predicate=Q(date_joined__isnull=True)),
                expected_sql=CompiledSQL(clause="date_joined IS NULL"),
                python_evaluations=[
                    PythonEvaluation(actual=None, expected=True),
                    PythonEvaluation(actual="", expected=False),
                ],
            ),
            LookupScenario(
                name="false matches non-null values",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="isnull",
                value="false",
                sql_value=False,
                expected_lookup=CompiledLookup(predicate=Q(date_joined__isnull=False)),
                expected_sql=CompiledSQL(clause="date_joined IS NOT NULL"),
                python_evaluations=[
                    PythonEvaluation(actual=None, expected=False),
                    PythonEvaluation(actual="", expected=True),
                ],
            ),
        ]
