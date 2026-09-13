from django.db.models import Q

from bloomerp.lookups.builtins.address_contains import ADDRESS_CONTAINS
from bloomerp.lookups.definition import CompiledLookup
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario, PythonEvaluation


class TestAddressContainsLookup(BloomerpLookupTestCase):
    lookup = ADDRESS_CONTAINS

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [LookupScenario(
            name="selected address components",
            application_field=lambda: self.get_application_field("description"),
            field_path="address",
            expression="address_contains",
            value={"city": "Ghent", "country": "BE"},
            expected_lookup=CompiledLookup(
                predicate=(
                    Q(address__city__icontains="Ghent")
                    & Q(address__country__iexact="BE")
                )
            ),
            python_evaluations=[
                PythonEvaluation(
                    actual={"city": "Ghent", "country": "be"},
                    expected=True,
                ),
                PythonEvaluation(
                    actual={"city": "Brussels", "country": "BE"},
                    expected=False,
                ),
            ],
        )]
