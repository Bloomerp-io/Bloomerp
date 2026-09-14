from django.db.models import Q

from bloomerp.lookups.builtins.values_in import VALUES_IN
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestValuesInLookup(BloomerpLookupTestCase):
    lookup = VALUES_IN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="CSV integers",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="values_in",
                value="20, 25, 29",
                sql_value=(20, 25, 29),
                expected_lookup=CompiledLookup(predicate=Q(age__in=(20, 25, 29))),
                expected_sql=CompiledSQL(
                    clause="age IN (%s, %s, %s)",
                    parameters=(20, 25, 29),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="25", expected=True),
                    PythonEvaluation(actual="24", expected=False),
                    PythonEvaluation(actual=["25"], expected=False),
                ],
            ),
            LookupScenario(
                name="empty candidate list",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="in",
                value=[],
                expected_lookup=CompiledLookup(predicate=Q(age__in=())),
                expected_sql=CompiledSQL(clause="1 = 0"),
            ),
        ]
