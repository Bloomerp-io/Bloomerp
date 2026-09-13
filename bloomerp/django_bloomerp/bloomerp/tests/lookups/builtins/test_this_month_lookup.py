from datetime import date
from unittest.mock import patch

from django.db.models import Q

from bloomerp.lookups.builtins.this_month import THIS_MONTH
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestThisMonthLookup(BloomerpLookupTestCase):
    lookup = THIS_MONTH

    def extendedSetup(self) -> None:
        patcher = patch(
            "bloomerp.lookups.builtins.this_month.timezone.localdate",
            return_value=date(2026, 9, 12),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="current local month",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="this_month",
                value=True,
                expected_lookup=CompiledLookup(
                    predicate=Q(
                        date_joined__gte=date(2026, 9, 1),
                        date_joined__lt=date(2026, 10, 1),
                    )
                ),
                expected_sql=CompiledSQL(
                    clause="date_joined >= %s AND date_joined < %s",
                    parameters=(date(2026, 9, 1), date(2026, 10, 1)),
                ),
                python_evaluations=[
                    PythonEvaluation(actual=date(2026, 9, 1), expected=True),
                    PythonEvaluation(actual=date(2026, 9, 30), expected=True),
                    PythonEvaluation(actual=date(2026, 10, 1), expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            )
        ]
