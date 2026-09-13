from django.db.models import Q

from bloomerp.lookups.builtins.contains import CONTAINS
from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    SQLLookupContext,
)
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestContainsLookup(BloomerpLookupTestCase):
    lookup = CONTAINS

    def get_test_scenarios(self) -> list[LookupScenario]:
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
                    clause="first_name ILIKE %s",
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
                    clause="LOWER(first_name) LIKE LOWER(%s)",
                    parameters=("%av%",),
                ),
                sql_context=SQLLookupContext(
                    field_path="first_name",
                    dialect="sqlite",
                ),
            ),
        ]
