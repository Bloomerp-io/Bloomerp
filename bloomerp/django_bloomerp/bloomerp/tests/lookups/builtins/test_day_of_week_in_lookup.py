from datetime import date

from django.db.models import Q

from bloomerp.lookups.builtins.day_of_week_in import DAY_OF_WEEK_IN
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestDayOfWeekInLookup(BloomerpLookupTestCase):
    lookup = DAY_OF_WEEK_IN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [LookupScenario(
            name="weekend weekdays",
            application_field=lambda: self.get_application_field("date_joined"),
            field_path="date_joined",
            expression="day_of_week_in",
            value="5, 6",
            sql_value=(5, 6),
            expected_lookup=CompiledLookup(
                predicate=Q(date_joined__iso_week_day__in=(6, 7))
            ),
            expected_sql=CompiledSQL(
                clause="EXTRACT(ISODOW FROM date_joined) IN (%s, %s)",
                parameters=(6, 7),
            ),
            python_evaluations=[
                PythonEvaluation(actual=date(2026, 9, 12), expected=True),
                PythonEvaluation(actual=date(2026, 9, 14), expected=False),
            ],
        )]
