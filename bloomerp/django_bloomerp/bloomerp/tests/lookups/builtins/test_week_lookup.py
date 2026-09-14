from datetime import date

from bloomerp.lookups.builtins.week import WEEK
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.date_part_scenarios import date_part_scenario


class TestWeekLookup(BloomerpLookupTestCase):
    lookup = WEEK

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [date_part_scenario(self, "week", 37, date(2026, 9, 12), date(2026, 9, 14))]
