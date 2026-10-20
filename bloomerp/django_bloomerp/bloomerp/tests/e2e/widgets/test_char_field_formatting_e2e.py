"""Exercise CharField formatting through real layout-driven forms and native input."""

from functools import partial

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


class TestCharFieldFormattingE2E(BloomerpE2ETestCase):
    """Verify typed and inserted text is normalized before being submitted."""

    auto_create_customers = False

    def _prepare_layout(self, config: dict[str, str | None]) -> None:
        """Select a minimal Todo layout with the requested title input settings."""
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
                        LayoutItem(id=fields.get(field="title").pk, config=config),
                        LayoutItem(id=fields.get(field="priority").pk),
                        LayoutItem(id=fields.get(field="status").pk),
                    ],
                )
            ]
        ).model_dump(mode="json")
        preference.save(update_fields=["layout"])

    def _type_title(self) -> None:
        """Type lowercase text and spaces using native keyboard input events."""
        field = self.page.locator('input[name="title"]')
        field.fill("")
        field.press_sequentially("hello world")

    def _insert_title(self) -> None:
        """Insert mixed case and whitespace in one native input event, like paste."""
        field = self.page.locator('input[name="title"]')
        field.fill("")
        field.focus()
        self.page.keyboard.insert_text("MiXeD text")

    def _expect_title(self, value: str) -> None:
        """Assert the submitted input value itself obeys the selected rules."""
        expect(self.page.locator('input[name="title"]')).to_have_value(value)

    def _edit_middle(self) -> None:
        """Insert text in the middle and verify removed whitespace keeps the caret."""
        field = self.page.locator('input[name="title"]')
        for _ in range(len("MIXEDTEXT") - 1):
            field.press("ArrowLeft")
        field.press_sequentially(" x")
        expect(field).to_have_value("MXIXEDTEXT")
        field.press("y")
        expect(field).to_have_value("MXYIXEDTEXT")

    def _save_title(self, title: str, todo: Todo | None = None) -> None:
        """Submit the normalized title and verify its persisted database value."""
        url = todo.get_absolute_url() if todo else reverse(get_create_view_url(Todo))
        with self.expect_response_for(url, method="POST") as pending:
            self.page.locator("#object-crud-container-save-button").click()
        self.assertIn(pending.value.status, [200, 302])
        if todo:
            todo.refresh_from_db()
            self.assertEqual(todo.title, title)
        else:
            self.assertTrue(
                Todo.objects.filter(title=title).exists(),
                f"Saved titles: {list(Todo.objects.values_list('title', flat=True))}",
            )

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Cover every option, null defaults, combined rules, and detail-page saves."""
        scenarios: list[E2ERequestScenario] = []
        for config, typed, inserted in [
            ({"formatting": "uppercase"}, "HELLO WORLD", "MIXED TEXT"),
            ({"formatting": "lowercase"}, "hello world", "mixed text"),
            ({"spaces": "dash"}, "hello-world", "MiXeD-text"),
            ({"spaces": "underscore"}, "hello_world", "MiXeD_text"),
            (
                {"formatting": "uppercase", "spaces": "remove"},
                "HELLOWORLD",
                "MIXEDTEXT",
            ),
            ({"formatting": None, "spaces": None}, "hello world", "MiXeD text"),
        ]:
            actions = [
                E2EAction(
                    name="Type lowercase text containing spaces",
                    execute=self._type_title,
                    validators=partial(self._expect_title, typed),
                ),
                E2EAction(
                    name="Insert mixed-case text containing spaces",
                    execute=self._insert_title,
                    validators=partial(self._expect_title, inserted),
                ),
            ]
            if config.get("spaces") == "remove":
                actions.append(
                    E2EAction(
                        name="Edit the middle without moving the caret",
                        execute=self._edit_middle,
                    )
                )
                inserted = "MXYIXEDTEXT"
            actions.append(
                E2EAction(
                    name="Save the actual transformed value",
                    execute=partial(self._save_title, inserted),
                )
            )
            scenarios.append(
                E2ERequestScenario(
                    name=f"Create form formats input with {config}",
                    user=self.admin_user,
                    url=reverse(get_create_view_url(Todo)),
                    prepare=partial(self._prepare_layout, config),
                    actions=actions,
                )
            )
        todo = Todo.objects.create(title="Existing mixed title")
        scenarios.append(
            E2ERequestScenario(
                name="Detail form applies uppercase and dashes when editing existing text",
                user=self.admin_user,
                url=todo.get_absolute_url(),
                prepare=partial(
                    self._prepare_layout, {"formatting": "uppercase", "spaces": "dash"}
                ),
                actions=[
                    E2EAction(
                        name="Preserve stored text until edited",
                        execute=partial(self._expect_title, todo.title),
                    ),
                    E2EAction(
                        name="Type and normalize on the detail form",
                        execute=self._type_title,
                        validators=partial(self._expect_title, "HELLO-WORLD"),
                    ),
                    E2EAction(
                        name="Persist the formatted edit",
                        execute=partial(self._save_title, "HELLO-WORLD", todo),
                    ),
                ],
            )
        )
        return scenarios
