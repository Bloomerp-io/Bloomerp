from datetime import date

from django.db.models import Q

from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.tests.base import LookupScenario, PythonEvaluation


def date_part_scenario(test_case, part, value, matching, non_matching):
    return LookupScenario(
        name=f"extract {part}",
        application_field=lambda: test_case.get_application_field("date_joined"),
        field_path="date_joined",
        expression=part,
        value=str(value),
        sql_value=value,
        expected_lookup=CompiledLookup(predicate=Q(**{f"date_joined__{part}": value})),
        expected_sql=CompiledSQL(
            clause=f"EXTRACT({part.upper()} FROM date_joined) = %s",
            parameters=(value,),
        ),
        python_evaluations=[
            PythonEvaluation(actual=matching, expected=True),
            PythonEvaluation(actual=non_matching, expected=False),
            PythonEvaluation(actual=None, expected=False),
        ],
    )
