from datetime import date
from unittest.mock import patch

from bloomerp.lookups.builtins.this_week import THIS_WEEK
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.relative_date_scenarios import relative_date_scenario


class TestThisWeekLookup(BloomerpLookupTestCase):
    lookup = THIS_WEEK

    def extendedSetup(self):
        patcher = patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [relative_date_scenario(self, "this_week", date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 12), date(2026, 9, 14))]
