from datetime import date
from unittest.mock import patch

from bloomerp.lookups.builtins.this_quarter import THIS_QUARTER
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.relative_date_scenarios import relative_date_scenario


class TestThisQuarterLookup(BloomerpLookupTestCase):
    lookup = THIS_QUARTER

    def extendedSetup(self):
        patcher = patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [relative_date_scenario(self, "this_quarter", date(2026, 7, 1), date(2026, 10, 1), date(2026, 9, 30), date(2026, 10, 1))]
