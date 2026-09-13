from django.db.models import Q

from bloomerp.lookups.builtins.greater_or_equal_than import GREATER_THAN_OR_EQUAL
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestGreaterThanOrEqualLookup(BloomerpLookupTestCase):
    lookup = GREATER_THAN_OR_EQUAL

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="serialized integer value",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="gte",
                value="25",
                sql_value=25,
                expected_lookup=CompiledLookup(predicate=Q(age__gte=25)),
                expected_sql=CompiledSQL(
                    clause="age >= %s",
                    parameters=(25,),
                ),
                python_evaluations=[
                    PythonEvaluation(actual=26, expected=True),
                    PythonEvaluation(actual=25, expected=True),
                    PythonEvaluation(actual=24, expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            )
        ]
