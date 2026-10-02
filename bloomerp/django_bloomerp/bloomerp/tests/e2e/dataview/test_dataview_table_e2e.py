from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import E2EAction, E2ERequestScenario, e2e_test_case
from bloomerp.utils.models import get_list_view_url
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import expect


class TestDataviewTableE2E(e2e_test_case.BloomerpE2ETestCase):
    """Verify that wide tables remain accessible through horizontal scrolling."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise overflowing columns in the regular and split table layouts."""
        return [
            E2ERequestScenario(
                name="Scroll overflowing table columns",
                user=self.admin_user,
                prepare=self.prepare_table,
                url=reverse(get_list_view_url(Todo)),
                actions=[
                    E2EAction(
                        name="Scroll to the last visible field",
                        execute=self.assert_table_scrolls,
                    )
                ],
            ),
            E2ERequestScenario(
                name="Scroll overflowing split-view table columns",
                user=self.admin_user,
                prepare=self.prepare_split_table,
                url=reverse(get_list_view_url(Todo)),
                actions=[
                    E2EAction(
                        name="Scroll to the last field inside the list pane",
                        execute=self.assert_table_scrolls,
                    )
                ],
            ),
        ]

    def prepare_table(self, split_view_enabled: bool = False) -> None:
        """Configure enough real Todo fields to overflow a narrow viewport."""
        content_type = ContentType.objects.get_for_model(Todo)
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": content_type.pk},
        )
        fields = [
            ApplicationField.get_by_field(Todo, field_name)
            for field_name in (
                "title",
                "status",
                "priority",
                "assigned_to",
                "requested_by",
                "required_by",
                "effort",
                "datetime_created",
                "datetime_updated",
            )
        ]
        preference.view_type = "table"
        preference.split_view_enabled = split_view_enabled
        preference.set_visible_field_ids("table", [field.pk for field in fields])
        preference.save(
            update_fields=["view_type", "split_view_enabled", "display_fields"]
        )
        Todo.objects.get_or_create(title="Horizontal overflow regression")
        self.page.set_viewport_size({"width": 800, "height": 700})

    def prepare_split_table(self) -> None:
        """Enable the split layout before testing the same table scroll contract."""
        self.prepare_table(split_view_enabled=True)

    def assert_table_scrolls(self) -> None:
        """Check actual overflow, scroll movement, and access to the last header."""
        table = self.page.locator("#data-view-data-section table")
        expect(table).to_be_visible()
        expect(table.locator("thead th button[hx-get]")).to_have_count(9)
        wrapper = table.locator("..")
        wrapper_box = wrapper.bounding_box()
        self.assertIsNotNone(wrapper_box)
        self.assertLessEqual(wrapper_box["x"] + wrapper_box["width"], 801)
        self.assertEqual(
            self.page.evaluate(
                "getComputedStyle(document.querySelector('#data-view-data-section table').parentElement).overflowX"
            ),
            "auto",
        )
        self.assertTrue(
            self.page.evaluate(
                "document.querySelector('#data-view-data-section table').parentElement.scrollWidth > "
                "document.querySelector('#data-view-data-section table').parentElement.clientWidth"
            )
        )
        self.page.evaluate(
            "document.querySelector('#data-view-data-section table').parentElement.scrollLeft = "
            "document.querySelector('#data-view-data-section table').parentElement.scrollWidth"
        )
        self.assertGreater(
            self.page.evaluate(
                "document.querySelector('#data-view-data-section table').parentElement.scrollLeft"
            ),
            0,
        )
        last_header_box = table.locator("thead th").last.bounding_box()
        self.assertIsNotNone(last_header_box)
        self.assertGreaterEqual(last_header_box["x"], wrapper_box["x"])
        self.assertLessEqual(
            last_header_box["x"] + last_header_box["width"],
            wrapper_box["x"] + wrapper_box["width"] + 1,
        )
