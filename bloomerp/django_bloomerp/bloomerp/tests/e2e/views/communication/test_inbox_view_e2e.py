"""Browser regressions for inbox selection, conversation navigation and preview closing."""

import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from bloomerp.models import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.communication.inbox.user_inbox_preference import UserInboxPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario


class TestInboxViewE2E(BloomerpE2ETestCase):
    """Exercise the inbox list and its detail panel through real browser events."""

    view_name = "inbox"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Seed a conversation and a following message for a complete navigation journey."""
        account = EmailAccount.objects.create(email_address="navigation@example.com")
        inbox = Inbox.objects.create(name="Navigation inbox", user=self.admin_user)
        PreferenceManager(self.admin_user).select(inbox)
        folder = InboxFolder.objects.create(inbox=inbox, type="email", related_object_id=str(account.pk))
        preference = UserInboxPreference.get_for_user(self.admin_user)
        preference.selected_inbox_folder = folder
        preference.save(update_fields=["selected_inbox_folder"])
        now = timezone.now()
        self.anchor = InboxItem.objects.create(
            folder=folder, item_type="email", title="Conversation anchor", is_read=True,
            datetime_received=now, related_item_id="<anchor@example.com>",
            raw_meta_data={"mailbox": "INBOX", "message_id": "<anchor@example.com>", "outbound_body_html": "<p>Anchor preview</p>"},
        )
        self.following = InboxItem.objects.create(
            folder=folder, item_type="email", title="Following message", is_read=False,
            datetime_received=now - timedelta(minutes=1), related_item_id="<following@example.com>",
            raw_meta_data={"mailbox": "INBOX", "outbound_body_html": "<p>Following preview</p>"},
        )
        self.reply = InboxItem.objects.create(
            folder=folder, item_type="email", title="Related reply", is_read=True,
            datetime_received=now - timedelta(minutes=2), related_item_id="<reply@example.com>",
            raw_meta_data={"mailbox": "INBOX", "in_reply_to": "<anchor@example.com>"},
        )
        return [E2ERequestScenario(
            name="Read-state presets serialize and execute shared filters",
            user=self.admin_user, url=reverse("inbox"), prepare=self.use_dark_theme,
            actions=[E2EAction(name="Apply Read and Unread presets", execute=self.apply_filter_presets)],
        ), E2ERequestScenario(
            name="Navigate collapsed and expanded conversations and close/reopen the preview",
            user=self.admin_user, url=reverse("inbox"), prepare=self.use_dark_theme,
            actions=[
                E2EAction(name="Focus search with the advertised shortcut", execute=self.focus_search),
                E2EAction(name="Skip collapsed children and style the entire row", execute=self.navigate_conversation),
                E2EAction(name="Close the detail and reopen it", execute=self.close_and_reopen_preview),
                E2EAction(name="Render the composer in dark mode", execute=self.check_composer_colors),
            ],
        )]

    def use_dark_theme(self) -> None:
        """Load the inbox in dark mode to verify both preview title colors."""
        self.context.add_init_script("localStorage.setItem('bloomerp_theme_preference', 'dark');")

    def focus_search(self) -> None:
        """Focus the compact search from another control using the Dataview shortcut."""
        row = self.page.locator(f"#inbox-item-{self.anchor.pk} [data-inbox-row-button]")
        expect(row).to_be_visible()
        row.press("ControlOrMeta+/")
        search = self.page.get_by_role("textbox", name="Search inbox", exact=True)
        expect(search).to_be_focused()
        tooltip = self.page.locator('[data-shortcut="mod+/"] [data-shortcut-tooltip]')
        search.hover()
        expect(tooltip).to_be_visible()
        expect(tooltip).to_contain_text("Search")

    def navigate_conversation(self) -> None:
        """Keep hidden replies out of arrow navigation and include them after expansion."""
        anchor = self.page.locator(f"#inbox-item-{self.anchor.pk} [data-inbox-row-button]")
        following = self.page.locator(f"#inbox-item-{self.following.pk} [data-inbox-row-button]")
        reply = self.page.locator(f"#inbox-item-{self.reply.pk} [data-inbox-row-button]")
        expect(anchor).to_be_visible()
        self.page.locator("#inbox-search-input").press("ArrowDown")
        expect(anchor).to_be_focused()
        selected = self.page.locator("summary[data-inbox-selected]")
        expect(selected).to_be_visible()
        expect(selected).to_have_css("box-shadow", re.compile(r".*2px.*"))
        expect(selected).not_to_have_css("background-color", "rgba(0, 0, 0, 0)")
        anchor.press("ArrowDown")
        expect(following).to_be_focused()
        following.press("ArrowUp")
        expect(anchor).to_be_focused()
        anchor.press("Space")
        expect(reply).to_be_visible()
        anchor.press("ArrowDown")
        expect(reply).to_be_focused()
        reply.press("ArrowDown")
        expect(following).to_be_focused()
        following.press("ArrowUp")
        reply.press("ArrowUp")
        anchor.press("Space")
        anchor.press("ArrowDown")
        expect(following).to_be_focused()

    def close_and_reopen_preview(self) -> None:
        """Retain focus after the read-status swap, render dark titles, and close/reopen the panel."""
        row = self.page.locator(f"#inbox-item-{self.following.pk} [data-inbox-row-button]")
        panel = self.page.locator("#resizable-div-inbox-resizable")
        row.press("Enter")
        close = self.page.get_by_role("button", name="Close message", exact=True)
        expect(close).to_be_visible()
        expect(row).to_be_focused()
        self.following.refresh_from_db()
        self.assertTrue(self.following.is_read)
        detail = self.page.locator('[data-inbox-item-detail="true"]')
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(detail.locator("header .text-gray-950")).to_have_css("color", "oklch(0.967 0.001 286.375)")
        expect(detail.locator("h1")).to_have_css("color", "oklch(0.967 0.001 286.375)")
        self.page.keyboard.press("ArrowUp")
        anchor = self.page.locator(f"#inbox-item-{self.anchor.pk} [data-inbox-row-button]")
        expect(anchor).to_be_focused()
        self.page.keyboard.press("ArrowDown")
        expect(row).to_be_focused()
        close.click()
        expect(panel).to_be_hidden()
        expect(row).to_be_focused()
        expect(self.page.locator("#inbox-item-render-target")).to_be_empty()
        row.press("Enter")
        expect(close).to_be_visible()
        expect(panel).to_be_visible()
        expect(row).to_be_focused()
        expect(self.page.locator("[data-inbox-selected]")).to_contain_text("Following message")

    def check_composer_colors(self) -> None:
        """Keep the new-message heading and sender selector readable in dark mode."""
        self.page.locator('[data-inbox-action-key="new_email"][data-inbox-action-level="folder"]').click()
        composer = self.page.locator('[bloomerp-component="email-editor"]')
        expect(composer).to_be_visible()
        expect(composer.locator("h2")).to_have_css("color", "oklch(0.967 0.001 286.375)")
        expect(composer.locator('[name="email_account_id"]')).to_have_css("color", "oklch(0.967 0.001 286.375)")

    def apply_filter_presets(self) -> None:
        """Exercise the browser's preset serialization through the rendered list endpoint."""
        anchor = self.page.locator(f"#inbox-item-{self.anchor.pk} [data-inbox-row-button]")
        following = self.page.locator(f"#inbox-item-{self.following.pk} [data-inbox-row-button]")
        expect(anchor).to_be_visible()
        dropdown = self.page.locator("#select-filter-dropdown")
        dropdown.locator('[aria-haspopup="true"]').click()
        dropdown.locator('[data-inbox-filter-key="is_read"]').click()
        expect(following).to_be_hidden()
        expect(anchor).to_be_visible()
        dropdown.locator('[aria-haspopup="true"]').click()
        dropdown.locator('[data-inbox-filter-key="unread"]').click()
        expect(anchor).to_be_hidden()
        expect(following).to_be_visible()
