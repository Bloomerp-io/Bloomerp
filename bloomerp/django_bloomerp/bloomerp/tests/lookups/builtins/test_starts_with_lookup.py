from django.db.models import Q

from bloomerp.lookups.builtins.starts_with import STARTS_WITH
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestStartsWithLookup(BloomerpLookupTestCase):
    lookup = STARTS_WITH

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="canonical expression",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="starts_with",
                value="Dav",
                expected_lookup=CompiledLookup(
                    predicate=Q(first_name__startswith="Dav")
                ),
                expected_sql=CompiledSQL(
                    clause="first_name LIKE %s",
                    parameters=("Dav%",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="David", expected=True),
                    PythonEvaluation(actual="McDavid", expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            ),
            LookupScenario(
                name="Django expression alias",
                application_field=lambda: self.get_application_field("last_name"),
                field_path="last_name",
                expression="startswith",
                value="Smi",
                expected_lookup=CompiledLookup(
                    predicate=Q(last_name__startswith="Smi")
                ),
            ),
        ]
