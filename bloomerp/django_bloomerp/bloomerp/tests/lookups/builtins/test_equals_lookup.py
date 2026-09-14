from django.db.models import Q

from bloomerp.lookups.builtins.equals import EQUALS
from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestEqualsLookup(BloomerpLookupTestCase):
    lookup = EQUALS
    create_foreign_models = True

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [
            LookupScenario(
                name="empty exact expression",
                application_field=lambda: self.get_application_field("first_name"),
                field_path="first_name",
                expression="",
                value="David",
                expected_lookup=CompiledLookup(predicate=Q(first_name="David")),
                expected_sql=CompiledSQL(
                    clause="first_name = %s",
                    parameters=("David",),
                ),
                python_evaluations=[
                    PythonEvaluation(actual="David", expected=True),
                    PythonEvaluation(actual="david", expected=False),
                    PythonEvaluation(actual=["David", "Sarah"], expected=False),
                ],
            ),
            LookupScenario(
                name="integer value is normalized by its Django field",
                application_field=lambda: self.get_application_field("age"),
                field_path="age",
                expression="equals",
                value="25",
                sql_value=25,
                expected_lookup=CompiledLookup(predicate=Q(age=25)),
                expected_sql=CompiledSQL(
                    clause="age = %s",
                    parameters=(25,),
                ),
            ),
            LookupScenario(
                name="exact alias",
                application_field=lambda: self.get_application_field("last_name"),
                field_path="last_name",
                expression="exact",
                value="Smith",
                expected_lookup=CompiledLookup(predicate=Q(last_name="Smith")),
            ),
            LookupScenario(
                name="null uses SQL null semantics",
                application_field=lambda: self.get_application_field("date_joined"),
                field_path="date_joined",
                expression="eq",
                value=None,
                expected_lookup=CompiledLookup(predicate=Q(date_joined=None)),
                expected_sql=CompiledSQL(clause="date_joined IS NULL"),
            ),
            LookupScenario(
                name="resolved nested path with an exact alias",
                application_field=lambda: self.get_application_field(
                    "name",
                    self.PlanetModel,
                ),
                field_path="country__planet__name",
                expression="eq",
                value="Earth",
                expected_lookup=CompiledLookup(
                    predicate=Q(country__planet__name="Earth")
                ),
            ),
            LookupScenario(
                name="resolved deeply nested path with implicit equality",
                application_field=lambda: self.get_application_field(
                    "name",
                    Initiative,
                ),
                field_path="parent__parent__parent__parent__name",
                expression="",
                value="Cool initiative",
                expected_lookup=CompiledLookup(
                    predicate=Q(
                        parent__parent__parent__parent__name="Cool initiative"
                    )
                ),
            ),
        ]
