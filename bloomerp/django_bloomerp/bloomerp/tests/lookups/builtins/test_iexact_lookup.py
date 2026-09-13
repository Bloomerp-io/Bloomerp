from django.db.models import Q

from bloomerp.lookups.builtins.iexact import IEXACT
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestIExactLookup(BloomerpLookupTestCase):
    lookup = IEXACT

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="case-insensitive exact text",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="iexact",
                value="david",
                expected_lookup=CompiledLookup(
                    predicate=Q(first_name__iexact="david")
                ),
                expected_sql=CompiledSQL(
                    clause="LOWER(first_name) = LOWER(%s)",
                    parameters=("david",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="David", expected=True),
                    PythonEvaluation(actual="DAVID", expected=True),
                    PythonEvaluation(actual="Davina", expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            )
        ]
