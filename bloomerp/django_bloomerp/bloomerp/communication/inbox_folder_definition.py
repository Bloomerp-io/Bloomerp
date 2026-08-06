from dataclasses import dataclass
from typing import Callable, Literal, Optional, TYPE_CHECKING, Type
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.db.models import Model
from bloomerp.communication.emails.actions import delete_email, mark_email_as_read, query_emails, render_email
from bloomerp.communication.inbox_sources import InboxEventSource, InboxJobSource, InboxSignalSource
from bloomerp.communication.system_messages.base import SystemMessage
from bloomerp.components.communication.emails.download_attachment import download_attachment  # noqa: F401
from bloomerp.components.communication.emails.new_email import new_email
from bloomerp.components.communication.emails.reply_to_email import (
    email_reply_is_available,
    reply_to_email,
)
from bloomerp.components.communication.emails.sync_emails import sync_emails
from bloomerp.utils.base_type_definition import BaseTypeDefinition

from bloomerp.utils.requests import parse_bool_parameter, render_message, render_page_refresh_with_message

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

INBOX_ITEMS_TARGET = "inbox-items"
INBOX_ITEM_RENDER_TARGET = "inbox-item-render-target"
INBOX_MESSAGE_TARGET = "inbox-message-target"

def on_query_default(filters: dict[str, str] | None, folder: "InboxFolder", _: bool) -> QuerySet["InboxItem"]:
    """
    Default on_query function that filters InboxItem objects based on the provided filters and folder.

    Args:
        filters (dict[str, str] | None): A dictionary of filter parameters.
        folder (InboxFolder): The inbox folder to filter items from.
        _ (bool): An unused boolean parameter.

    Returns:
        QuerySet[InboxItem]: A QuerySet of filtered InboxItem objects.
    """
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    queryset = InboxItem.objects.filter(folder=folder)
    
    filters = filters.copy() if filters else {}
    search_query = filters.pop("q", None)
    
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query) | Q(snippet__icontains=search_query)
        )
    
    return queryset.order_by("-datetime_received", "-datetime_created").filter(**filters)


def on_query_all(filters: dict[str, str] | None, folder: "InboxFolder", _: bool) -> QuerySet["InboxItem"]:
    """
    Query all inbox items across every folder in the selected inbox.

    Args:
        filters: Optional filter parameters such as q and is_read.
        folder: The aggregate folder used to identify the inbox.
        _: Deep query flag, unused for aggregate local queries.

    Returns:
        A distinct queryset of matching InboxItem objects.
    """
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    queryset = InboxItem.objects.filter(folder__inbox=folder.inbox)

    search_query = (filters or {}).get("q")
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query)
            | Q(snippet__icontains=search_query)
            | Q(actor__icontains=search_query)
        )

    is_read_filter = (filters or {}).get("is_read")
    if is_read_filter is not None:
        queryset = queryset.filter(is_read=parse_bool_parameter(is_read_filter))

    return queryset.distinct().order_by("-datetime_received", "-datetime_created")


@dataclass
class InboxActionDefinition:
    key : str
    name : str
    icon : Optional[str] = None
    is_primary_action: bool = True
    execution_func : Callable[[HttpRequest, "InboxItem | InboxFolder"], HttpResponse] = lambda request,_: render_message(request, "Action executed successfully", "info")
    http_method: Literal["get", "post"] = "get"
    target: Literal['modal', 'items', 'message', 'render-item'] = "message"
    availability_func: Optional[Callable[["InboxItem | InboxFolder"], bool]] = None

    def is_available_for(self, target: "InboxItem | InboxFolder") -> bool:
        """Return whether this action can be used for the selected target."""
        return self.availability_func(target) if self.availability_func else True

@dataclass
class InboxItemTypeDefinition:
    # Unique identifier for the inbox item type
    key: str 
    
    # Human-readable name for the inbox item type
    name: str
    
    # Human-readable plural name
    name_plural: Optional[str] = None
    
    # Optional icon name for the inbox item type, used in the UI
    icon: Optional[str] = None
    
    # Optional source model associated with the inbox item type
    source_model: Optional[str] = None 
    
    # Optional callable that takes an InboxItem and returns a string representation. This can be used to customize how the inbox item is displayed.
    on_render: Optional[Callable[["InboxItem", HttpRequest], str]] = None
    
    # Optional callable that takes an InboxItem and executes a delete action
    on_delete: Optional[Callable[["InboxItem", HttpRequest], None]] = lambda item, _: item.delete()
    
    # Optional callable that takes an InboxItem and executes a mark as read action
    on_mark_as_read: Optional[Callable[["InboxItem", HttpRequest], None]] = lambda item, _: (setattr(item, 'is_read', True), item.save())

    # Optional list of actions that can be performed on the inbox item type
    actions: Optional[list[InboxActionDefinition]] = None
    
    
@dataclass
class InboxFolderTypeFilterDefinition:
    key : str
    
    # Human-readable name for the filter
    name : str
    
    # Dictionary of filter parameters that can be applied to the inbox type. The keys are the filter names, and the values are the corresponding filter values.
    filters:dict[str, str] = None
    
    is_subfolder: bool = False
    

@dataclass
class InboxFolderTypeDefinition:
    # Unique identifier for the inbox type
    key: str 
    
    # Human-readable name for the inbox type
    name: str 
    
    # Description of the inbox type, used in the UI
    description: Optional[str] = None
    
    # Default on_rendering function that converts the InboxItem to a string representation
    item_type : Optional[InboxItemTypeDefinition] = None
    
    # Icon name for the inbox type, used in the UI
    icon: Optional[str] = None
    
    # Optional list of filters that can be applied to the inbox type
    filters: Optional[list[InboxFolderTypeFilterDefinition] | Callable[["InboxFolder"], list[InboxFolderTypeFilterDefinition]]] = None 
    
    # Optional source model associated with the inbox type
    source_model: Optional[str] = None 
    
    # Optional list of actions that can be performed on the inbox type
    actions: Optional[list[InboxActionDefinition]] = None 
    
    # Optional callable that takes a dictionary of filter parameters and returns a QuerySet of InboxItem objects. This can be used to customize the on_query for fetching inbox items based on the filters applied.
    on_query: Callable[[dict[str, str], "InboxFolder", bool], QuerySet["InboxItem"]] = on_query_default
    
    # Is aggregate
    is_aggregate:bool = False

    # Aggregate functions that takes an inbox folder and returns a QuerySet of InboxFolder objects
    aggregate_func: Optional[Callable[["InboxFolder"], QuerySet["InboxFolder"]]] = None
    
    # Is default folder
    is_default: bool = False

    default_sources: Optional[list[InboxSignalSource | InboxJobSource | InboxEventSource]] = None

    def resolve_filters(self, folder: "InboxFolder") -> list[InboxFolderTypeFilterDefinition]:
        if not self.filters:
            return []
        if callable(self.filters):
            return self.filters(folder) or []
        return self.filters
    
    def get_source_model_class(self) -> Optional[Type[Model]]:
        """
        Retrieves the source model class associated with the inbox type.

        Returns:
            Type[Model]: The source model class if defined, otherwise None.
        """
        if self.source_model:
            from django.apps import apps
            return apps.get_model(self.source_model)
        return None
    
    def get_item_type(self) -> Optional[InboxItemTypeDefinition]:
        """
        Retrieves the InboxItemTypeDefinition associated with this inbox type.

        Returns:
            InboxItemTypeDefinition: The definition of the inbox item type if defined, otherwise None.
        """
        return self.item_type
    
# Define common actions for inbox items and folders
MARK_ALL_AS_READ_ACTION = InboxActionDefinition(
    key="mark_all_as_read",
    name="Mark All as Read",
    icon="fa fa-check-double"
)

MARK_INBOX_ITEM_AS_READ_ACTION = InboxActionDefinition(
    key="mark_as_read",
    name="Mark as Read",
    icon="fa fa-check",
    http_method="post",
    execution_func=lambda request, item: (
        item.get_inbox_item_type().on_mark_as_read(item, request),
        render_message(request, "Item marked as read", "success")
    )[-1]
)

DELETE_INBOX_ITEM_ACTION = InboxActionDefinition(
    key="delete_inbox_item",
    name="Delete Inbox Item",
    icon="fa fa-trash",
    is_primary_action=False,
    http_method="post",
    execution_func=lambda request, item: (
        item.get_inbox_item_type().on_delete(item, request),
        render_page_refresh_with_message(request, "Item deleted successfully", "success")
    )[-1]
)

REPLY_TO_EMAIL_ACTION = InboxActionDefinition(
    key="reply_to_email",
    name="Reply",
    icon="fa fa-reply",
    target="render-item",
    execution_func=reply_to_email,
    availability_func=email_reply_is_available,
)

DELETE_INBOX_FOLDER_ACTION = InboxActionDefinition(
    key="delete_inbox_folder",
    name="Delete Inbox Folder",
    icon="fa fa-trash",
    is_primary_action=False,
    execution_func=lambda request, folder: (
        folder.delete(), 
        render_page_refresh_with_message(request, "Inbox folder deleted successfully", "success")
    )[-1]
)

# Define common filters
IS_READ_FILTER = InboxFolderTypeFilterDefinition(
    key="is_read",
    name="Read",
    filters={"is_read": "true"}
)
UNREAD_FILTER = InboxFolderTypeFilterDefinition(
    key="unread",
    name="Unread",
    filters={"is_read": "false"}
)


class InboxFolderType(BaseTypeDefinition):
    ALL = InboxFolderTypeDefinition(
        key="all",
        name="All",
        description="All inbox items across all folders",
        icon="fa fa-inbox",
        actions=[
            MARK_ALL_AS_READ_ACTION,
            DELETE_INBOX_FOLDER_ACTION
        ],
        on_query=on_query_all,
        is_aggregate=True,
        aggregate_func=lambda inbox_folder: (),
        is_default=True
    )
    
    IN_APP_NOTIFICATIONS = InboxFolderTypeDefinition(
        key="in_app_notifications",
        name="Notifications",
        description="All in-app notifications",
        icon="fa fa-bell",
        actions=[
            MARK_ALL_AS_READ_ACTION,
            #
            DELETE_INBOX_FOLDER_ACTION,
        ],
        on_query=lambda filters, folder, _: (
            on_query_default(filters, folder, _).filter(item_type="notification")
        ),
        item_type=InboxItemTypeDefinition(
            key="notification",
            name="Notification",
            name_plural="Notifications",
            icon="fa fa-bell",
            on_render=SystemMessage.resolve_render,
            actions=[
                MARK_INBOX_ITEM_AS_READ_ACTION,
                DELETE_INBOX_ITEM_ACTION,
            ],
        ),
        is_default=True,
        default_sources=[
            InboxEventSource(
                key="workflow.result",
                folder_qs_resolver="bloomerp.communication.system_messages.workflow.resolve_workflow_notification_folders",
                handler="bloomerp.communication.system_messages.workflow.handle_workflow_result",
                run_async=False,
            ),
            InboxEventSource(
                key="system.message",
                folder_qs_resolver=(
                    "bloomerp.communication.system_messages.inbox_sources."
                    "resolve_system_message_folders"
                ),
                handler=(
                    "bloomerp.communication.system_messages.inbox_sources."
                    "handle_system_message"
                ),
                run_async=False,
            ),
            InboxSignalSource(
                key="form.submission.created",
                signal="django.db.models.signals.post_save",
                sender="bloomerp.models.forms.form_submission.FormSubmission",
                dispatch_uid="bloomerp.inbox.form_submission.created",
                predicate=(
                    "bloomerp.communication.system_messages.form_submission."
                    "should_notify_form_submission"
                ),
                folder_qs_resolver=(
                    "bloomerp.communication.system_messages.form_submission."
                    "resolve_form_submission_folders"
                ),
                handler=(
                    "bloomerp.communication.system_messages.form_submission."
                    "handle_form_submission"
                ),
                run_async=False,
            ),
            InboxSignalSource(
                key="workflow.approval_required",
                signal="django.db.models.signals.post_save",
                sender="bloomerp.models.automation.workflow_run_step.WorkflowRunStep",
                folder_qs_resolver="bloomerp.communication.system_messages.signals.workflow_approval_required.resolve",
                handler="bloomerp.communication.system_messages.signals.workflow_approval_required.handle",
                predicate="bloomerp.communication.system_messages.signals.workflow_approval_required.predicate",
                dispatch_uid="workflow.approval_required",
                run_async=False,
            )
        ],
        filters=lambda _: [
            UNREAD_FILTER,
            IS_READ_FILTER,
            *(
                [
                    InboxFolderTypeFilterDefinition(
                        key="type_" + message_type.value.key,
                        name=message_type.value.name,
                        filters={"raw_meta_data__system_message_type": message_type.value.key},
                    )
                    for message_type in SystemMessage
                ]
            )
        ]
    )
    
    EMAIL = InboxFolderTypeDefinition(
        key="email",
        name="Emails",
        description="Emails from a connected email account",
        icon="fa fa-envelope",
        source_model="bloomerp.EmailAccount",
        on_query=query_emails,
        actions=[
            InboxActionDefinition(
                key="new_email",
                name="New Email",
                icon="fa fa-pen-to-square",
                target="render-item",
                execution_func=new_email
            ),
            MARK_ALL_AS_READ_ACTION,
            InboxActionDefinition(
                key="sync_emails",
                name="Sync Emails",
                icon="fa fa-sync",
                http_method="get",
                target="modal",
                execution_func=sync_emails
            ),
            DELETE_INBOX_FOLDER_ACTION,    
        ],
        filters=lambda folder: [
            # Regular filters
            UNREAD_FILTER,
            IS_READ_FILTER,
            # Dynamic filters based on the related email account's mailboxes
            *(
                [
                    InboxFolderTypeFilterDefinition(
                        key="mailbox_" + mailbox,
                        name=mailbox,
                        filters={"mailbox": mailbox},
                        is_subfolder=True
                    ) for mailbox in folder.related_object().mailboxes
                ] if folder.related_object() else []
            )
        ],
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
                folder_qs_resolver="bloomerp.communication.emails.sync.resolve_email_folders",
                handler="bloomerp.communication.emails.sync.dispatch_due_email_syncs_source",
                schedule="*/2 * * * *",
            ),
            InboxEventSource(
                key="email.sync.account",
                folder_qs_resolver="bloomerp.communication.emails.sync.resolve_email_folders",
                handler="bloomerp.communication.emails.sync.handle_email_account_sync",
                run_async=True,
            ),
        ]
    )
    
    @classmethod
    def get_item_type_by_key(cls, key: str) -> InboxItemTypeDefinition:
        """
        Retrieves the InboxItemTypeDefinition associated with the given key.

        Args:
            key (str): The unique identifier for the inbox item type.

        Returns:
            InboxItemTypeDefinition: The definition of the inbox item type.

        Raises:
            ValueError: If no matching inbox item type is found for the given key.
        """
        for item in cls:
            if item.value.item_type and item.value.item_type.key == key:
                return item.value.item_type
        raise ValueError(f"No matching inbox item type found for key: {key}")
    
    
    
    
    
    
    
