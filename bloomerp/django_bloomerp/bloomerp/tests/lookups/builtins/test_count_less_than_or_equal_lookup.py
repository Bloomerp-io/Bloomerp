from bloomerp.lookups.builtins.count_less_than_or_equal import COUNT_LESS_THAN_OR_EQUAL
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.count_scenarios import count_scenario


class TestCountLessThanOrEqualLookup(BloomerpLookupTestCase):
    lookup = COUNT_LESS_THAN_OR_EQUAL

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [count_scenario(self, "count_less_than_or_equal", "lte", "<=", 3, True)]
