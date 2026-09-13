from datetime import date

from bloomerp.lookups.builtins.month import MONTH
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.date_part_scenarios import date_part_scenario


class TestMonthLookup(BloomerpLookupTestCase):
    lookup = MONTH

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [date_part_scenario(self, "month", 9, date(2026, 9, 12), date(2026, 8, 12))]
