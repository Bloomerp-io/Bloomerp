from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.base_user import AbstractBaseUser
from django.urls import reverse
from playwright.sync_api import Response, expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestForeignFieldWidgetE2E(BloomerpE2ETestCase):
    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise inline selection, replacement, and deletion in the real form."""
        return [
            E2ERequestScenario(
                name="Keyboard editing keeps foreign-key tokens inline and the cursor in the input",
                user=self.admin_user,
                url=reverse(get_create_view_url(model=Todo)),
                actions=[
                    E2EAction(name="Select the first relation", execute=self.select_admin),
                    E2EAction(name="Replace the relation", execute=self.select_normal_user),
                    E2EAction(name="Delete the relation", execute=self.delete_selection),
                ],
            ),
        ]

    def select_admin(self) -> None:
        """Choose a relation in an initially empty widget."""
        self.select_user(self.admin_user)

    def select_normal_user(self) -> None:
        """Replace the existing relation with another authorized search result."""
        self.select_user(self.normal_user)

    def select_user(self, user: AbstractBaseUser) -> None:
        """Type a real search and commit its result with Enter, preserving focus."""
        widget = self.page.locator(
            '[bloomerp-component="foreign-field-widget"][data-field-name="requested_by"]'
        )
        expect(widget).to_have_attribute("data-component-initialized", "true")
        search = widget.locator('input[type="text"]')
        search.fill(user.get_username())
        result = self.page.locator(
            f'.foreign-field-dropdown:visible li[data-id="{user.pk}"]'
        )
        expect(result).to_be_visible()
        search.press("Enter")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        expect(widget.locator('input[data-generated="true"]')).to_have_value(str(user.pk))
        token = widget.locator(".foreign-field-control .foreign-field-badge")
        expect(token).to_have_count(1)
        expect(token).to_contain_text(str(user))
        control_box = widget.locator(".foreign-field-control").bounding_box()
        token_box = token.bounding_box()
        self.assertIsNotNone(control_box)
        self.assertIsNotNone(token_box)
        self.assertGreaterEqual(token_box["y"], control_box["y"])
        self.assertLessEqual(
            token_box["y"] + token_box["height"],
            control_box["y"] + control_box["height"],
        )
        self.assertEqual(self.page.url, self.url(reverse(get_create_view_url(model=Todo))))

    def delete_selection(self) -> None:
        """Delete the selected token without submitting the form or losing focus."""
        widget = self.page.locator(
            '[bloomerp-component="foreign-field-widget"][data-field-name="requested_by"]'
        )
        expect(widget).to_have_attribute("data-component-initialized", "true")
        search = widget.locator('input[type="text"]')
        search.press("Backspace")
        expect(widget.locator(".foreign-field-badge")).to_have_count(0)
        expect(widget.locator('input[data-empty-value="true"]')).to_have_value("")
        expect(search).to_be_focused()

    def test_advanced_query_keeps_selection_behavior_after_search(self) -> None:
        """
        Use case: Search inside a foreign-field widget's advanced query modal.
        Expected result: Clicking a result after the search selects it in the widget.
        """
        # 1. Open the Todo create form and launch Requested By's advanced query.
        self._authenticate_browser(self.admin_user)
        self.goto(reverse(get_create_view_url(model=Todo)))
        widget = self.page.locator(
            '[bloomerp-component="foreign-field-widget"][data-field-name="requested_by"]'
        )
        expect(widget).to_have_attribute("data-component-initialized", "true")
        widget.locator('input[type="text"]').focus()
        self.page.locator('.foreign-field-dropdown:visible [data-action="advanced-query"]').click()

        modal = self.page.locator('[data-modal-instance-of="advanced-query-modal"]')
        dataview = modal.locator('[bloomerp-component="foreign-field-dataview"]')
        expect(dataview).to_be_visible()

        # 2. Search for the admin user and verify the custom component stays in use.
        username = self.admin_user.get_username()

        def is_final_search(response: Response) -> bool:
            """Identify the final advanced-search response for the selected user."""
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
