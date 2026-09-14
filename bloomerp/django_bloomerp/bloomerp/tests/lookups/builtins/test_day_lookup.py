from datetime import date

from bloomerp.lookups.builtins.day import DAY
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.date_part_scenarios import date_part_scenario


class TestDayLookup(BloomerpLookupTestCase):
    lookup = DAY

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [date_part_scenario(self, "day", 12, date(2026, 9, 12), date(2026, 9, 13))]
