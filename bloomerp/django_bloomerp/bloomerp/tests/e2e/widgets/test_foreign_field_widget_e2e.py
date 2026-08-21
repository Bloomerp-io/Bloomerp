from urllib.parse import parse_qs, urlsplit

from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.e2e.base import BaseE2ETestCase
from bloomerp.utils.models import get_create_view_url


class TestForeignFieldWidgetE2E(BaseE2ETestCase):
    def test_advanced_query_keeps_selection_behavior_after_search(self):
        """
        Use case: Search inside a foreign-field widget's advanced query modal.
        Expected result: Clicking a result after the search selects it in the widget.
        """
        # 1. Open the Todo create form and launch Requested By's advanced query.
        self.login_as_admin()
        self.goto(reverse(get_create_view_url(model=Todo)))
        widget = self.page.locator(
            '[bloomerp-component="foreign-field-widget"][data-field-name="requested_by"]'
        )
        widget.locator('input[type="text"]').focus()
        widget.locator('[data-action="advanced-query"]').click()

        modal = self.page.locator("#advanced-query-modal")
        dataview = modal.locator('[bloomerp-component="foreign-field-dataview"]')
        expect(dataview).to_be_visible()

        # 2. Search for the admin user and verify the custom component stays in use.
        username = self.admin_user.get_username()

        def is_final_search(response) -> bool:
            parsed_url = urlsplit(response.url)
            return (
                "/components/dataview/" in parsed_url.path
                and parse_qs(parsed_url.query).get("q") == [username]
            )

        with self.page.expect_response(is_final_search):
            dataview.locator('input[name="q"]').fill(username)

        expect(dataview).to_have_attribute(
            "bloomerp-component",
            "foreign-field-dataview",
        )

        # 3. Click a swapped-in cell and verify the foreign field receives the user.
        dataview.locator(
            f'[bloomerp-component="datatable-cell"]'
            f'[data-object-id="{self.admin_user.pk}"]'
        ).first.dblclick()

        selected_input = widget.locator(
            'input[type="hidden"][name="requested_by"][data-generated="true"]'
        )
        expect(selected_input).to_have_value(str(self.admin_user.pk))
        expect(modal).to_be_hidden()
