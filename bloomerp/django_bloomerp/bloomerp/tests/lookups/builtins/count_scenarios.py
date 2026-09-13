from django.db.models import Count, Q

from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.tests.base import LookupScenario, PythonEvaluation


def count_scenario(test_case, lookup_id, expression, operator, value, expected):
    alias = "_sub_initiatives_count"
    return LookupScenario(
        name=lookup_id.replace("_", " "),
        application_field=lambda: test_case.get_application_field(
            "sub_initiatives",
            Initiative,
        ),
        field_path="sub_initiatives",
        expression=lookup_id,
        value=str(value),
        sql_value=value,
        expected_lookup=CompiledLookup(
            predicate=Q(**{f"{alias}__{expression}": value}),
            annotations={alias: Count("sub_initiatives")},
        ),
        expected_sql=CompiledSQL(
            clause=f"COUNT(sub_initiatives) {operator} %s",
            parameters=(value,),
        ),
        python_evaluations=[
            PythonEvaluation(actual=[1, 2, 3], expected=expected),
            PythonEvaluation(actual=None, expected=False),
        ],
    )
