from datetime import date
from unittest.mock import patch

from bloomerp.lookups.builtins.yesterday import YESTERDAY
from bloomerp.tests.base import BloomerpLookupTestCase, LookupScenario
from bloomerp.tests.lookups.builtins.relative_date_scenarios import relative_date_scenario


class TestYesterdayLookup(BloomerpLookupTestCase):
    lookup = YESTERDAY

    def get_test_scenarios(self) -> list[LookupScenario]:
        with patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12)):
            return [relative_date_scenario(self, "yesterday", date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 11), date(2026, 9, 12))]

    def extendedSetup(self):
        patcher = patch("bloomerp.lookups.builtins.utils.timezone.localdate", return_value=date(2026, 9, 12))
        patcher.start()
        self.addCleanup(patcher.stop)
