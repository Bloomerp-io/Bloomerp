"""Pagination contracts for grouped and ordinary inbox list responses."""

from django.http import HttpResponse
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRenderInboxFolderPagination(BloomerpComponentTestCase):
    view_name = "components_render_inbox_folder_items"

    def prepare_items(self, scenario: RequestScenario) -> None:
        """Seed enough notification items to paginate without provider behavior."""
        inbox = Inbox.objects.create(name="Pagination", user=self.admin_user)
        folder = InboxFolder.objects.create(inbox=inbox, type="in_app_notifications")
        InboxItem.objects.bulk_create(
            [
                InboxItem(
                    folder=folder, item_type="notification", title=f"Invoice {index}"
                )
                for index in range(205)
            ]
        )
        scenario.view_kwargs = {"folder_id": str(folder.pk)}

    def full_page(self, response: HttpResponse) -> bool:
        """Verify a page contains exactly one hundred item buttons and a next cursor."""
        return (
            response.content.count(b"data-inbox-row-button") == 100
            and b"page=3" in response.content
        )

    def last_page(self, response: HttpResponse) -> bool:
        """Verify the last page contains only the remaining items and no loader."""
        return (
            response.content.count(b"data-inbox-row-button") == 5
            and b"data-inbox-page-loader" not in response.content
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise pagination control parsing and preservation of semantic filters."""
        return [
            RequestScenario(
                name="Second page preserves the search",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"page": 2, "q": "Invoice"},
                expected=ExpectedResult(
                    response_validators=[
                        self.full_page,
                        self.contains_text("q=Invoice"),
                    ]
                ),
            ),
            RequestScenario(
                name="Last page has the remaining five messages",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"page": 3},
                expected=ExpectedResult(response_validators=self.last_page),
            ),
        ]
