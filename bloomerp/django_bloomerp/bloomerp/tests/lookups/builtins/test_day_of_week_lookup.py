from datetime import date

from django.db.models import Q

from bloomerp.lookups.builtins.day_of_week import DAY_OF_WEEK
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestDayOfWeekLookup(BloomerpLookupTestCase):
    lookup = DAY_OF_WEEK

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [LookupScenario(
            name="Monday uses the UI zero-based weekday",
            application_field=lambda: self.get_application_field("date_joined"),
            field_path="date_joined",
            expression="day_of_week",
            value="0",
            sql_value=0,
            expected_lookup=CompiledLookup(predicate=Q(date_joined__iso_week_day=1)),
            expected_sql=CompiledSQL(
                clause="EXTRACT(ISODOW FROM date_joined) = %s",
                parameters=(1,),
            ),
            python_evaluations=[
                PythonEvaluation(actual=date(2026, 9, 7), expected=True),
                PythonEvaluation(actual=date(2026, 9, 8), expected=False),
            ],
        )]
