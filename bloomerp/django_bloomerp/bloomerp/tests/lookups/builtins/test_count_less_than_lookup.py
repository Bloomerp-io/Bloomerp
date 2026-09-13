from bloomerp.lookups.builtins.count_less_than import COUNT_LESS_THAN
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.count_scenarios import count_scenario


class TestCountLessThanLookup(BloomerpLookupTestCase):
    lookup = COUNT_LESS_THAN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [count_scenario(self, "count_less_than", "lt", "<", 4, True)]
