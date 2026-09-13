from datetime import date

from django.db.models import Q

from bloomerp.lookups.builtins.not_in import NOT_IN
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL, SQLLookupContext
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestNotInLookup(BloomerpLookupTestCase):
    lookup = NOT_IN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="CSV integers",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="not_in",
                value="20, 25, 29",
                sql_context=SQLLookupContext(
                    field_path="age",
                    sql_type="integer",
                    nullable=False,
                ),
                sql_value=(20, 25, 29),
                expected_lookup=CompiledLookup(predicate=~Q(age__in=(20, 25, 29))),
                expected_sql=CompiledSQL(
                    clause="age NOT IN (%s, %s, %s)",
                    parameters=(20, 25, 29),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="24", expected=True),
                    PythonEvaluation(actual="25", expected=False),
                    PythonEvaluation(actual=["25"], expected=True),
                ],
            ),
            LookupScenario(
                name="empty candidate list",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="nin",
                value=[],
                expected_lookup=CompiledLookup(predicate=~Q(age__in=())),
                expected_sql=CompiledSQL(clause="1 = 1"),
            ),
            LookupScenario(
                name="nullable field preserves null rows",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="nin",
                value=["2026-09-12", "2026-09-13"],
                sql_context=SQLLookupContext(
                    field_path="date_joined",
                    sql_type="date",
                    nullable=True,
                ),
                sql_value=(date(2026, 9, 12), date(2026, 9, 13)),
                expected_lookup=CompiledLookup(
                    predicate=~Q(
                        date_joined__in=(date(2026, 9, 12), date(2026, 9, 13))
                    )
                ),
                expected_sql=CompiledSQL(
                    clause=(
                        "(date_joined NOT IN (%s, %s) OR date_joined IS NULL)"
                    ),
                    parameters=(date(2026, 9, 12), date(2026, 9, 13)),
                ),
            ),
        ]
