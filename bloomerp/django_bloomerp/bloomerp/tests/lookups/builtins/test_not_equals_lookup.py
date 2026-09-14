from datetime import date

from django.db.models import Q

from bloomerp.lookups.builtins.not_equals import NOT_EQUALS
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL, SQLLookupContext
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestNotEqualsLookup(BloomerpLookupTestCase):
    lookup = NOT_EQUALS

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="serialized integer value",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="not_equals",
                value="25",
                sql_context=SQLLookupContext(
                    field_path="age",
                    sql_type="integer",
                    nullable=False,
                ),
                sql_value=25,
                expected_lookup=CompiledLookup(predicate=~Q(age=25)),
                expected_sql=CompiledSQL(
                    clause="age <> %s",
                    parameters=(25,),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="25", expected=False),
                    PythonEvaluation(actual="26", expected=True),
                    PythonEvaluation(actual=["25"], expected=True),
                ],
            ),
            LookupScenario(
                name="null uses SQL null semantics",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="ne",
                value=None,
                expected_lookup=CompiledLookup(predicate=~Q(date_joined=None)),
                expected_sql=CompiledSQL(clause="date_joined IS NOT NULL"),
            ),
            LookupScenario(
                name="nullable field preserves null rows",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="ne",
                value="2026-09-12",
                sql_context=SQLLookupContext(
                    field_path="date_joined",
                    sql_type="date",
                    nullable=True,
                ),
                sql_value=date(2026, 9, 12),
                expected_lookup=CompiledLookup(
                    predicate=~Q(date_joined=date(2026, 9, 12))
                ),
                expected_sql=CompiledSQL(
                    clause="(date_joined <> %s OR date_joined IS NULL)",
                    parameters=(date(2026, 9, 12),),
                ),
            ),
        ]
