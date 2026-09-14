from bloomerp.lookups.builtins.count_greater_than_or_equal import COUNT_GREATER_THAN_OR_EQUAL
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.count_scenarios import count_scenario


class TestCountGreaterThanOrEqualLookup(BloomerpLookupTestCase):
    lookup = COUNT_GREATER_THAN_OR_EQUAL

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [count_scenario(self, "count_greater_than_or_equal", "gte", ">=", 3, True)]
