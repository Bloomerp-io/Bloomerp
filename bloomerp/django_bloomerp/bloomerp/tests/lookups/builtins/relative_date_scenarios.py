from datetime import date

from django.db.models import Q

from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import LookupScenario, PythonEvaluation


def relative_date_scenario(test_case, lookup_id, start, end, inside, outside):
    return LookupScenario(
        name=lookup_id.replace("_", " "),
        application_field=lambda: test_case.get_application_field("date_joined"),
        field_path="date_joined",
        expression=lookup_id,
        value=True,
        expected_lookup=CompiledLookup(
            predicate=Q(date_joined__gte=start, date_joined__lt=end)
        ),
        expected_sql=CompiledSQL(
            clause="date_joined >= %s AND date_joined < %s",
            parameters=(start, end),
        ),
        python_evaluations=[
            PythonEvaluation(actual=inside, expected=True),
            PythonEvaluation(actual=outside, expected=False),
            PythonEvaluation(actual=None, expected=False),
        ],
    )
