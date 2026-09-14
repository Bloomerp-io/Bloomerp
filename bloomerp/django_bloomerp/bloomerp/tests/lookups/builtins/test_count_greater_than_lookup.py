from bloomerp.lookups.builtins.count_greater_than import COUNT_GREATER_THAN
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.count_scenarios import count_scenario


class TestCountGreaterThanLookup(BloomerpLookupTestCase):
    lookup = COUNT_GREATER_THAN

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [count_scenario(self, "count_greater_than", "gt", ">", 2, True)]
