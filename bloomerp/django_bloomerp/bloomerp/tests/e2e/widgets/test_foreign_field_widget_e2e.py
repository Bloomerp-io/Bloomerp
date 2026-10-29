from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.contenttypes.models import ContentType

from bloomerp.form_behaviors.builtins import ADD_FILTER
from bloomerp.form_behaviors.definition import BehaviorAction, BehaviorConfig, FormBehavior
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.services.preference_services import PreferenceManager
from django.urls import reverse
from playwright.sync_api import Response, expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestForeignFieldWidgetE2E(BloomerpE2ETestCase):
    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise token editing and draft-dependent choices in the real form."""
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
            E2ERequestScenario(
                name="Form behaviors filter relationship search and advanced choices",
                user=self.admin_user,
                prepare=self.configure_choice_behavior,
                url=reverse(get_create_view_url(model=Todo)),
                actions=[
                    E2EAction(name="Choose source and inspect restricted choices", execute=self.filter_for_admin),
                    E2EAction(name="Change source and inspect advanced selection", execute=self.filter_for_normal_user),
                    E2EAction(name="Clear source and offer no choices", execute=self.clear_filter_source),
                ],
            ),
        ]

    def configure_choice_behavior(self) -> None:
        """Restrict assignee choices to the user selected in Requested By."""
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": ContentType.objects.get_for_model(Todo).pk},
        )
        fields = {field.field: field.pk for field in ApplicationField.get_for_model(Todo)}
        preference.layout = FieldLayout(rows=[LayoutRow(columns=1, items=[
            LayoutItem(id=fields["title"]),
            LayoutItem(id=fields["requested_by"], config={"behaviors": BehaviorConfig(behaviors=[FormBehavior(
                id="filter-assignees", events=["initial", "change"], actions=[BehaviorAction(
                    action=ADD_FILTER, target_field="assigned_to", config={"filters": [{
                        "connector": "AND", "conditions": [{"field_path": "id", "lookup_id": "equals", "value": "{{ object.requested_by }}"}],
                    }]},
                )],
            )]).to_storage()}),
            LayoutItem(id=fields["assigned_to"]),
        ])]).model_dump(mode="json")
        preference.save(update_fields=["layout"])

    def is_behavior_response(self, response: Response) -> bool:
        """Wait for a real successful behavior evaluation before opening choices."""
        return "/components/form_behavior/execute/" in response.url and response.request.method == "POST"

    def filter_for_admin(self) -> None:
        """Resolve the draft user reference and narrow ordinary search results."""
        with self.page.expect_response(self.is_behavior_response) as response:
            self.select_user(self.admin_user)
        self.assertEqual(response.value.status, 200)
        self.assert_restricted_choices(self.admin_user)

    def assert_restricted_choices(self, user: AbstractBaseUser) -> None:
        """Open the target picker and verify only the selected source is offered."""
        widget = self.page.locator('[bloomerp-component="foreign-field-widget"][data-field-name="assigned_to"]')
        widget.locator('input[type="text"]').focus()
        results = self.page.locator('.foreign-field-dropdown:visible li[data-id]')
        expect(results).to_have_count(1)
        expect(results.first).to_have_attribute("data-id", str(user.pk))

    def filter_for_normal_user(self) -> None:
        """Replace the filter and prove the advanced picker receives the new restriction."""
        with self.page.expect_response(self.is_behavior_response) as response:
            self.select_user(self.normal_user)
        self.assertEqual(response.value.status, 200)
        self.assert_restricted_choices(self.normal_user)
        self.page.locator('.foreign-field-dropdown:visible [data-action="advanced-query"]').click()
        modal = self.page.locator('[data-modal-instance-of="advanced-query-modal"]')
        cells = modal.locator('[bloomerp-component="datatable-cell"][data-object-id]')
        expect(cells.first).to_be_visible()
        self.assertEqual({cell.get_attribute("data-object-id") for cell in cells.all()}, {str(self.normal_user.pk)})
        cells.first.dblclick()
        expect(modal).to_be_hidden()

    def clear_filter_source(self) -> None:
        """Clearing the dependency removes choices without silently clearing the target value."""
        with self.page.expect_response(self.is_behavior_response) as response:
            self.delete_selection()
        self.assertEqual(response.value.status, 200)
        widget = self.page.locator('[bloomerp-component="foreign-field-widget"][data-field-name="assigned_to"]')
        widget.locator('input[type="text"]').focus()
        expect(self.page.locator('.foreign-field-dropdown:visible')).to_contain_text("No results")
        expect(self.page.locator('.foreign-field-dropdown:visible li[data-id]')).to_have_count(0)
        expect(widget.locator('input[data-generated="true"]')).to_have_value(str(self.normal_user.pk))

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
