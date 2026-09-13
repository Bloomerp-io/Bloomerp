from bloomerp.lookups.builtins.count_equals import COUNT_EQUALS
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.count_scenarios import count_scenario


class TestCountEqualsLookup(BloomerpLookupTestCase):
    lookup = COUNT_EQUALS

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [count_scenario(self, "count_equals", "exact", "=", 3, True)]
