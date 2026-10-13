"""Exercise choice color changes on actual Todo create and detail pages."""

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.models import ApplicationField, FieldLayout, LayoutItem, LayoutRow, Todo
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestColoredChoicesWidgetE2E(BloomerpE2ETestCase):
    """Verify native select events update the configured color accent."""

    auto_create_customers = False

    def _prepare_layout(self) -> None:
        """Select a Todo layout with colored status choices and no unrelated fields."""
        fields = ApplicationField.get_for_model(Todo)
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": ContentType.objects.get_for_model(Todo).pk},
        )
        preference.layout = FieldLayout(
            rows=[
                LayoutRow(
                    columns=1,
                    items=[
                        LayoutItem(id=fields.get(field="title").pk),
                        LayoutItem(
                            id=fields.get(field="status").pk,
                            config={
                                "choice_colors": {
                                    "completed": "#00ff00",
                                    "scoped": "#ffff00",
                                    "retired": "#ff0000",
                                },
                            },
                        ),
                    ],
                )
            ]
        ).model_dump(mode="json")
        preference.save(update_fields=["layout"])

    def _select_completed(self) -> None:
        """Change the native status selector to the green choice."""
        self.page.locator('select[name="status"]').select_option("completed")

    def _expect_green(self) -> None:
        """Confirm the component applies the selected choice's green accent."""
        expect(self.page.locator('select[name="status"]')).to_have_css(
            "border-left-color", "rgb(0, 255, 0)"
        )

    def _select_scoped(self) -> None:
        """Change the native status selector to the yellow choice."""
        self.page.locator('select[name="status"]').select_option("scoped")

    def _expect_yellow(self) -> None:
        """Confirm changing choices updates the color without a page reload."""
        expect(self.page.locator('select[name="status"]')).to_have_css(
            "border-left-color", "rgb(255, 255, 0)"
        )

    def _select_uncolored(self) -> None:
        """Change the status to a value without a configured color."""
        self.page.locator('select[name="status"]').select_option("backlog")

    def _expect_cleared(self) -> bool:
        """Confirm an uncolored choice clears the inline color accent."""
        return (
            self.page.locator('select[name="status"]').evaluate(
                "element => element.style.borderLeft"
            )
            == ""
        )

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Verify create and detail pages use the same configured choice widget."""
        todo = Todo.objects.create(
            title="Colored choices browser test", status="completed"
        )
        actions = [
            E2EAction(
                name="Select green choice",
                execute=self._select_completed,
                validators=self._expect_green,
            ),
            E2EAction(
                name="Switch to yellow choice",
                execute=self._select_scoped,
                validators=self._expect_yellow,
            ),
            E2EAction(
                name="Clear accent for uncolored choice",
                execute=self._select_uncolored,
                validators=self._expect_cleared,
            ),
        ]
        return [
            E2ERequestScenario(
                name="Create view responds to native choice changes",
                user=self.admin_user,
                prepare=self._prepare_layout,
                url=reverse(get_create_view_url(model=Todo)),
                actions=actions,
            ),
            E2ERequestScenario(
                name="Detail view restores color and responds to changes",
                user=self.admin_user,
                prepare=self._prepare_layout,
                url=todo.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Restore saved green choice", execute=self._expect_green
                    ),
                    *actions,
                ],
            ),
        ]
