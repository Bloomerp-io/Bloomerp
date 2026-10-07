"""Exercise shared filter predicates at the inbox request boundary."""

import json
from unittest.mock import patch

from django.http import HttpResponse
from bloomerp.communication.builtins.emails.base_adapter import BloomerpEmail
from bloomerp.models.communication.email_account import EmailAccount

from bloomerp.communication.common.filters import UNREAD_FILTER, IS_READ_FILTER
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRenderInboxFilters(BloomerpComponentTestCase):
    """Keep shared conditions inside the selected folder and reject malformed filters."""

    view_name = "components_render_inbox_folder_items"

    def prepare_items(self, scenario: RequestScenario) -> None:
        """Seed distinct read states and notification types plus an out-of-scope control."""
        inbox = Inbox.objects.create(name="Filtered inbox", user=self.admin_user)
        folder = InboxFolder.objects.create(inbox=inbox, type="in_app_notifications")
        InboxItem.objects.create(
            folder=folder,
            item_type="notification",
            title="Unread invoice",
            is_read=False,
            raw_meta_data={"system_message_type": "general"},
        )
        InboxItem.objects.create(
            folder=folder,
            item_type="notification",
            title="Read submission",
            is_read=True,
            raw_meta_data={"system_message_type": "form_submission"},
        )
        other = InboxFolder.objects.create(inbox=inbox, type="in_app_notifications")
        InboxItem.objects.create(
            folder=other,
            item_type="notification",
            title="Other folder secret",
            is_read=False,
        )
        scenario.view_kwargs = {"folder_id": str(folder.pk)}

    def prepare_deep_search(self, scenario: RequestScenario) -> None:
        """Seed a read local email and a provider unread result in the selected mailbox."""
        inbox = Inbox.objects.create(name="Email filters", user=self.admin_user)
        account = EmailAccount.objects.create(
            name="Support", email_address="filters@example.com"
        )
        folder = InboxFolder.objects.create(
            inbox=inbox,
            type="email",
            related_object_id=str(account.pk),
        )
        InboxItem.objects.create(
            folder=folder,
            item_type="email",
            title="Read local email",
            is_read=True,
            raw_meta_data={"mailbox": "INBOX"},
        )
        scenario.view_kwargs = {"folder_id": str(folder.pk)}
        self.adapter_patch = patch(
            "bloomerp.communication.builtins.emails.actions._resolve_email_adapter_for_account"
        )
        self.provider_adapter = self.adapter_patch.start().return_value
        self.provider_adapter.search_emails.return_value = [
            BloomerpEmail(
                provider=account.provider,
                provider_message_id="provider-unread",
                email_account_id=str(account.pk),
                mailbox="INBOX",
                subject="Unread provider email",
                is_read=False,
            )
        ]

    def cleanup_deep_search(self, scenario: RequestScenario) -> None:
        """Release the provider mock after the deep-search request scenario."""
        self.adapter_patch.stop()

    def validate_deep_search(self, response: HttpResponse) -> bool:
        """Verify filtered local emptiness triggers the selected provider mailbox search."""
        self.provider_adapter.search_emails.assert_called_once_with(
            None, mailbox="INBOX", limit=50
        )
        return (
            "Unread provider email" in response.content.decode()
            and "Read local email" not in response.content.decode()
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover migrated presets, JSON traversal, AND/OR groups and invalid input."""
        unread = json.dumps([group.model_dump() for group in UNREAD_FILTER.filters])
        read = json.dumps([group.model_dump() for group in IS_READ_FILTER.filters])
        notification_type = json.dumps(
            [
                Filter(
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="raw_meta_data__system_message_type",
                            lookup_id="equals",
                            value="form_submission",
                        )
                    ],
                ).model_dump()
            ]
        )
        either_title = json.dumps(
            [
                Filter(
                    connector="OR",
                    conditions=[
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value="Unread invoice",
                        ),
                        FilterCondition(
                            field_path="title",
                            lookup_id="equals",
                            value="Other folder secret",
                        ),
                    ],
                ).model_dump()
            ]
        )
        return [
            RequestScenario(
                name="Shared unread predicate triggers provider search when local read emails exist",
                user=self.admin_user,
                prepare=self.prepare_deep_search,
                cleanup=self.cleanup_deep_search,
                query_params={
                    "filter": unread,
                    "mailbox": "INBOX",
                    "deep_search": "true",
                },
                expected=ExpectedResult(response_validators=self.validate_deep_search),
            ),
            RequestScenario(
                name="Unread preset applies shared boolean conditions",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"filter": unread},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Unread invoice"),
                        self.does_not_contain_text("Read submission"),
                        self.does_not_contain_text("Other folder secret"),
                    ]
                ),
            ),
            RequestScenario(
                name="Read preset composes with search",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"filter": read, "q": "submission"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Read submission"),
                        self.does_not_contain_text("Unread invoice"),
                    ]
                ),
            ),
            RequestScenario(
                name="Notification type uses a shared JSON-field condition",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"filter": notification_type},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Read submission"),
                        self.does_not_contain_text("Unread invoice"),
                    ]
                ),
            ),
            RequestScenario(
                name="OR conditions cannot expand the selected folder",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"filter": either_title},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Unread invoice"),
                        self.does_not_contain_text("Other folder secret"),
                    ]
                ),
            ),
            RequestScenario(
                name="Invalid JSON returns a filter error",
                user=self.admin_user,
                prepare=self.prepare_items,
                query_params={"filter": "not-json"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Invalid filter JSON"),
                        self.does_not_contain_text("Unread invoice"),
                    ]
                ),
            ),
        ]
