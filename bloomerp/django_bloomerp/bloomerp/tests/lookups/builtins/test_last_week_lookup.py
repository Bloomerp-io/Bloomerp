from datetime import date
from unittest.mock import patch

from bloomerp.lookups.builtins.last_week import LAST_WEEK
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.relative_date_scenarios import relative_date_scenario


class TestLastWeekLookup(BloomerpLookupTestCase):
    lookup = LAST_WEEK

    def extendedSetup(self):
        patcher = patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_test_scenarios(self) -> list[LookupScenario]:
        return [relative_date_scenario(self, "last_week", date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 2), date(2026, 9, 7))]
