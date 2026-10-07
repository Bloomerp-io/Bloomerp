"""Email folder and item registrations."""

from bloomerp.communication.builtins.emails.grouping import group_email_items
from typing import TYPE_CHECKING
from bloomerp.communication.definition import (
    InboxActionDefinition,
    InboxFolderTypeDefinition,
    InboxItemTypeDefinition,
    InboxFolderTypeFilterDefinition,
)
from bloomerp.communication.builtins.emails.actions import (
    query_emails,
    render_email,
    delete_email,
    mark_email_as_read,
)
from bloomerp.communication.builtins.emails.mailboxes import normalize_mailboxes
from bloomerp.communication.inbox_sources import InboxEventSource, InboxJobSource
from bloomerp.communication.common.actions import (
    MARK_ALL_AS_READ_ACTION,
    MARK_INBOX_ITEM_AS_READ_ACTION,
    DELETE_INBOX_ITEM_ACTION,
    DELETE_INBOX_FOLDER_ACTION,
    REPLY_TO_EMAIL_ACTION,
)
from bloomerp.communication.common.filters import UNREAD_FILTER, IS_READ_FILTER
from bloomerp.components.communication.emails.new_email import new_email
from bloomerp.components.communication.emails.sync_emails import sync_emails
from bloomerp.components.communication.emails.download_attachment import (
    download_attachment,  # noqa: F401
)

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


def email_filters(folder: "InboxFolder") -> list[InboxFolderTypeFilterDefinition]:
    """Expose provider mailbox keys with the account's configured labels and colors."""
    account = folder.related_object()
    mailboxes = normalize_mailboxes(account.mailboxes) if account else {}
    return [
        UNREAD_FILTER,
        IS_READ_FILTER,
        *[
            InboxFolderTypeFilterDefinition(
                key="mailbox_" + name,
                name=settings["label"],
                query_params={"mailbox": name},
                is_subfolder=True,
                color=settings["color"],
            )
            for name, settings in mailboxes.items()
        ],
    ]


EMAIL = InboxFolderTypeDefinition(
    key="email",
    name="Emails",
    description="Emails from a connected email account",
    icon="fa fa-envelope",
    source_model="bloomerp.EmailAccount",
    on_query=query_emails,
    on_group=group_email_items,
    actions=[
        InboxActionDefinition(
            key="new_email",
            name="New Email",
            icon="fa fa-pen-to-square",
            target="render-item",
            execution_func=new_email,
        ),
        MARK_ALL_AS_READ_ACTION,
        InboxActionDefinition(
            key="sync_emails",
            name="Sync Emails",
            icon="fa fa-sync",
            http_method="get",
            target="modal",
            execution_func=sync_emails,
        ),
        DELETE_INBOX_FOLDER_ACTION,
    ],
    filters=email_filters,
    item_type=InboxItemTypeDefinition(
        key="email",
        name="Email",
        name_plural="Emails",
        icon="fa fa-envelope",
        on_render=render_email,
        on_delete=delete_email,
        on_mark_as_read=mark_email_as_read,
        actions=[
            REPLY_TO_EMAIL_ACTION,
            MARK_INBOX_ITEM_AS_READ_ACTION,
            DELETE_INBOX_ITEM_ACTION,
        ],
    ),
    default_sources=[
        InboxJobSource(
            key="email.sync.dispatch",
            folder_qs_resolver="bloomerp.communication.builtins.emails.sync.resolve_email_folders",
            handler="bloomerp.communication.builtins.emails.sync.dispatch_due_email_syncs_source",
            schedule="*/2 * * * *",
        ),
        InboxEventSource(
            key="email.sync.account",
            folder_qs_resolver="bloomerp.communication.builtins.emails.sync.resolve_email_folders",
            handler="bloomerp.communication.builtins.emails.sync.handle_email_account_sync",
            run_async=True,
        ),
    ],
)
