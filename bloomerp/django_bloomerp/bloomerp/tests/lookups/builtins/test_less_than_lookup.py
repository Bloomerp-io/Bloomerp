from django.db.models import Q

from bloomerp.lookups.builtins.less_than import LESS_THAN
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestLessThanLookup(BloomerpLookupTestCase):
    lookup = LESS_THAN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="serialized integer value",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="lt",
                value="25",
                sql_value=25,
                expected_lookup=CompiledLookup(predicate=Q(age__lt=25)),
                expected_sql=CompiledSQL(
                    clause="age < %s",
                    parameters=(25,),
                ),
                python_evaluations=[
                    PythonEvaluation(actual=24, expected=True),
                    PythonEvaluation(actual=25, expected=False),
                    PythonEvaluation(actual=26, expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            )
        ]
