from playwright.sync_api import expect
from bloomerp.tests.e2e.dataview.test_dataview_e2e_mixin import TestDataviewE2EMixin


class TestDataviewTableE2E(TestDataviewE2EMixin):
    def extendedE2ESetup(self):
        pass

    def test_journey(self):
        """
        UC: use_case

        Expected Result: criteria
        """
        # 1. prepare_the_recording_state
        self.goto_todo_page()

        self.start_codegen()
