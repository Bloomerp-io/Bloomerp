from datetime import date

from bloomerp.lookups.builtins.year import YEAR
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.date_part_scenarios import date_part_scenario


class TestYearLookup(BloomerpLookupTestCase):
    lookup = YEAR

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [date_part_scenario(self, "year", 2026, date(2026, 9, 12), date(2025, 9, 12))]
