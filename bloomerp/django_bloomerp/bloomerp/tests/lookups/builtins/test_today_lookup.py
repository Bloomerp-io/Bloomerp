from datetime import date, datetime
from unittest.mock import patch

from django.db.models import Q

from bloomerp.lookups.builtins.today import TODAY
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestTodayLookup(BloomerpLookupTestCase):
    lookup = TODAY

    def extendedSetup(self) -> None:
        patcher = patch(
            "bloomerp.lookups.builtins.today.timezone.localdate",
            return_value=date(2026, 9, 12),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="current local date",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="today",
                value=True,
                expected_lookup=CompiledLookup(
                    predicate=Q(
                        date_joined__gte=date(2026, 9, 12),
                        date_joined__lt=date(2026, 9, 13),
                    )
                ),
                expected_sql=CompiledSQL(
                    clause="date_joined >= %s AND date_joined < %s",
                    parameters=(date(2026, 9, 12), date(2026, 9, 13)),
                ),
                python_evaluations=[
                    PythonEvaluation(actual=date(2026, 9, 12), expected=True),
                    PythonEvaluation(
                        actual=datetime(2026, 9, 12, 16, 30),
                        expected=True,
                    ),
                    PythonEvaluation(actual=date(2026, 9, 11), expected=False),
                    PythonEvaluation(actual=None, expected=False),
                ],
            )
        ]
