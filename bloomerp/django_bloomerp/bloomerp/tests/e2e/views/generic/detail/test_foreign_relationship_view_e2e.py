from functools import partial

from django.contrib.contenttypes.models import ContentType
from playwright.sync_api import expect

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.audit.activity_log import ActivityLog
from bloomerp.models.communication import Comment
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario


class TestForeignRelationshipViewE2E(BloomerpE2ETestCase):
    """Exercise related records without replacing the parent record's sidebar."""

    view_name = "todos_relationship"
    browser_context_options = {"viewport": {"width": 1920, "height": 1080}}

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Open an Initiative's Todo and keep each record's activity and comments separate."""
        self.initiative = Initiative.objects.create(name="Parent initiative")
        self.todo = Todo.objects.create(title="Related drawer todo", initiative=self.initiative)
        for record, marker in [(self.initiative, "Initiative"), (self.todo, "Todo")]:
            content_type = ContentType.objects.get_for_model(record)
            Comment.objects.create(
                content_type=content_type, object_id=str(record.pk),
                content=f"{marker} comment marker", created_by=self.admin_user,
            )
            ActivityLog.objects.create(
                content_type=content_type, object_id=str(record.pk),
                payload=[{"field": "title", "from": "Original", "to": f"{marker} activity marker"}],
            )
        self.preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": ContentType.objects.get_for_model(Todo).pk},
        )
        self.preference.view_type = "table"
        self.preference.display_fields = {"table": [ApplicationField.get_by_field(Todo, "title").pk]}
        self.preference.save()
        return [E2ERequestScenario(
            name=f"Related Todo sidebar stays separate from its Initiative ({mode})",
            prepare=partial(self.prepare_mode, mode),
            user=self.admin_user,
            url=self.initiative.get_absolute_url(),
            actions=[
                E2EAction(name="Open the Initiative's related Todos", execute=self.open_related_todos),
                E2EAction(name="Open the Todo in its detail pane", execute=self.open_todo),
                E2EAction(name="Switch Todo comments and activity", execute=self.check_todo_sidebar),
            ],
        ) for mode in (UserListViewPreference.ViewMode.SPLIT, UserListViewPreference.ViewMode.DRAWER)]

    def prepare_mode(self, mode: str) -> None:
        """Select the embedded presentation before each isolated browser journey."""
        self.preference.view_mode = mode
        self.preference.save(update_fields=["view_mode"])

    def open_related_todos(self) -> None:
        """Follow the Initiative's reverse relationship tab with its sidebar loaded."""
        self.parent_sidebar = self.page.locator("[data-detail-view-grid]").first.locator(
            ":scope > #resizable-div-detail-aside"
        )
        expect(self.parent_sidebar).to_contain_text("Initiative activity marker", timeout=15000)
        self.page.locator('[data-tab-type="folder"]').filter(
            has=self.page.locator('a[href$="/todos/"]')
        ).locator('[data-folder-toggle]').click()
        self.page.locator('[data-tab-strip] a[href$="/todos/"]').click()
        expect(self.page.locator(f'td[data-object-id="{self.todo.pk}"]')).not_to_have_count(0)

    def open_todo(self) -> None:
        """Double-click the related Todo and check its initial activity loads locally."""
        self.page.locator(
            f'td[data-object-id="{self.todo.pk}"][data-application-field-name="title"]'
        ).dblclick()
        self.todo_sidebar = self.page.locator(
            '[data-split-view-detail-pane] #resizable-div-detail-aside, '
            '[data-drawer-detail-pane] #resizable-div-detail-aside'
        )
        expect(self.todo_sidebar).to_contain_text("Todo activity marker")
        expect(self.todo_sidebar).not_to_contain_text("Initiative activity marker")
        expect(self.parent_sidebar).to_contain_text("Initiative activity marker", timeout=15000)
        expect(self.parent_sidebar).not_to_contain_text("Todo activity marker")

    def check_todo_sidebar(self) -> None:
        """Switch both sidebar tabs and assert the parent content is untouched."""
        self.todo_sidebar.locator('[data-detail-sidebar-view="comments"]').click()
        expect(self.todo_sidebar).to_contain_text("Todo comment marker")
        expect(self.todo_sidebar).not_to_contain_text("Initiative comment marker")
        expect(self.parent_sidebar).to_contain_text("Initiative activity marker", timeout=15000)
        expect(self.parent_sidebar).not_to_contain_text("Todo comment marker")
        self.todo_sidebar.locator('[data-detail-sidebar-view="activity"]').click()
        expect(self.todo_sidebar).to_contain_text("Todo activity marker")
        expect(self.parent_sidebar).to_contain_text("Initiative activity marker", timeout=15000)
