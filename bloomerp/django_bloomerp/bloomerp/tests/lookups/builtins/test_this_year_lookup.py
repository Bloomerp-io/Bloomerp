from datetime import date
from unittest.mock import patch

from bloomerp.lookups.builtins.this_year import THIS_YEAR
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.relative_date_scenarios import relative_date_scenario


class TestThisYearLookup(BloomerpLookupTestCase):
    lookup = THIS_YEAR

    def extendedSetup(self):
        patcher = patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [relative_date_scenario(self, "this_year", date(2026, 1, 1), date(2027, 1, 1), date(2026, 12, 31), date(2027, 1, 1))]
