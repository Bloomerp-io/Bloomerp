"""Exercise settings on a newly inserted detail-layout field in the browser."""

from django.contrib.contenttypes.models import ContentType
from playwright.sync_api import expect

from bloomerp.models import ApplicationField, FieldLayout, LayoutItem, LayoutRow, Todo
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario


class TestLoadedFieldSettingsE2E(BloomerpE2ETestCase):
    """Prove new-field settings survive the layout save and a full reload."""

    auto_create_customers = False

    def _prepare_layout(self) -> None:
        """Start with only title present so status must be added through the UI."""
        fields = ApplicationField.get_for_model(Todo)
        self.status = fields.get(field="status")
        self.preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": ContentType.objects.get_for_model(Todo).pk},
        )
        self.preference.layout = FieldLayout(rows=[LayoutRow(
            columns=1, items=[LayoutItem(id=fields.get(field="title").pk)],
        )]).model_dump(mode="json")
        self.preference.save(update_fields=["layout"])

    def _add_and_open_settings(self) -> None:
        """Add status and click its gear as soon as the new item appears."""
        self.page.locator("[data-layout-edit-toggle]").click()
        self.page.locator('[bloomerp-open-drawer="layout-drawer-items"]').click()
        self.page.locator(
            f'[data-layout-sidebar-item][data-layout-item-id="{self.status.pk}"]'
        ).click()
        self.page.keyboard.press("Escape")
        self.page.locator(
            f'[data-layout-grid] [data-layout-item-id="{self.status.pk}"] [data-layout-edit-item]'
        ).click()
        expect(self.page.locator('#field-display-option-modal input[name="label"]')).to_be_visible()

    def _save_settings(self) -> None:
        """Submit an edited label through the real display-options modal."""
        modal = self.page.locator("#field-display-option-modal")
        modal.locator('input[name="label"]').fill("New field progress")
        modal.get_by_role("button", name="Save display options").click()
        expect(modal.get_by_text("Display options saved.")).to_be_visible()
        self.preference.refresh_from_db()
        item = next(item for row in self.preference.layout_obj.rows for item in row.items
                    if str(item.id) == str(self.status.pk))
        self.assertEqual(item.config["label"], "New field progress")

    def _dismiss_and_reload(self) -> None:
        """Close settings, check refreshed markup, then verify persistence on reload."""
        self.page.locator('[bloomerp-close-modal="field-display-option-modal"]').click()
        selector = f'[data-layout-grid] [data-layout-item-id="{self.status.pk}"] [data-detail-label]'
        expect(self.page.locator(selector)).to_have_text("New Field Progress")
        self.page.reload()
        expect(self.page.locator(selector)).to_have_text("New Field Progress")

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Run the add, configure, save, dismiss, and reload regression journey."""
        todo = Todo.objects.create(title="New field settings browser test")
        return [E2ERequestScenario(
            name="Newly added field settings persist immediately and after reload",
            user=self.admin_user, prepare=self._prepare_layout,
            url=todo.get_absolute_url(),
            actions=[
                E2EAction(name="Add field and immediately open its settings", execute=self._add_and_open_settings),
                E2EAction(name="Save the new field label", execute=self._save_settings),
                E2EAction(name="Dismiss and reload the saved label", execute=self._dismiss_and_reload),
            ],
        )]
