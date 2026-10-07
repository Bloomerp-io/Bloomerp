"""Extensible inbox folder, item, action and grouping contracts."""

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional, TYPE_CHECKING, Type
from django.db.models import Model, QuerySet
from bloomerp.filters.definition import Filters
from django.http import HttpRequest, HttpResponse
from bloomerp.communication.inbox_sources import (
    InboxEventSource,
    InboxJobSource,
    InboxSignalSource,
)

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

INBOX_ITEMS_TARGET = "inbox-items"
INBOX_ITEM_RENDER_TARGET = "inbox-item-render-target"
INBOX_MESSAGE_TARGET = "inbox-message-target"


def default_query(
    filters: dict[str, str] | None, folder: "InboxFolder", deep: bool
) -> QuerySet["InboxItem"]:
    """Defer the common query implementation to avoid definition import cycles."""
    from bloomerp.communication.common.queries import on_query_default

    return on_query_default(filters, folder, deep)


def default_action(
    request: HttpRequest, target: "InboxItem | InboxFolder"
) -> HttpResponse:
    """Render the existing default informational action response."""
    from bloomerp.utils.requests import render_message

    return render_message(request, "Action executed successfully", "info")


def default_delete(item: "InboxItem", request: HttpRequest) -> None:
    """Delete a local inbox item."""
    item.delete()


def default_mark_as_read(item: "InboxItem", request: HttpRequest) -> None:
    """Persist the local read flag."""
    item.is_read = True
    item.save(update_fields=["is_read"])


@dataclass
class InboxActionDefinition:
    key: str
    name: str
    icon: Optional[str] = None
    is_primary_action: bool = True
    execution_func: Callable[[HttpRequest, "InboxItem | InboxFolder"], HttpResponse] = (
        default_action
    )
    http_method: Literal["get", "post"] = "get"
    target: Literal["modal", "items", "message", "render-item"] = "message"
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
    on_delete: Optional[Callable[["InboxItem", HttpRequest], None]] = default_delete

    # Optional callable that takes an InboxItem and executes a mark as read action
    on_mark_as_read: Optional[Callable[["InboxItem", HttpRequest], None]] = (
        default_mark_as_read
    )

    # Optional list of actions that can be performed on the inbox item type
    actions: Optional[list[InboxActionDefinition]] = None


@dataclass
class InboxFolderTypeFilterDefinition:
    """An inbox preset combining shared conditions with explicit provider query controls."""

    key: str

    # Human-readable name for the filter
    name: str

    # Shared predicate groups applied to the folder queryset.
    filters: Filters = field(default_factory=list)

    # Provider/query controls, such as the mailbox used for deep search.
    query_params: dict[str, str] = field(default_factory=dict)

    is_subfolder: bool = False
    
    color: str = ""


@dataclass
class InboxItemGroup:
    """One list representative and its related items, without provider body fetching."""

    item: "InboxItem"
    related_items: list["InboxItem"]
    key: str


@dataclass
class InboxFolderTypeDefinition:
    # Unique identifier for the inbox type
    key: str

    # Human-readable name for the inbox type
    name: str

    # Description of the inbox type, used in the UI
    description: Optional[str] = None

    # Default on_rendering function that converts the InboxItem to a string representation
    item_type: Optional[InboxItemTypeDefinition] = None

    # Icon name for the inbox type, used in the UI
    icon: Optional[str] = None

    # Optional list of filters that can be applied to the inbox type
    filters: Optional[
        list[InboxFolderTypeFilterDefinition]
        | Callable[["InboxFolder"], list[InboxFolderTypeFilterDefinition]]
    ] = None

    # Optional source model associated with the inbox type
    source_model: Optional[str] = None

    # Optional list of actions that can be performed on the inbox type
    actions: Optional[list[InboxActionDefinition]] = None

    # Optional callable that takes a dictionary of filter parameters and returns a QuerySet of InboxItem objects. This can be used to customize the on_query for fetching inbox items based on the filters applied.
    on_query: Callable[[dict[str, str], "InboxFolder", bool], QuerySet["InboxItem"]] = (
        default_query
    )

    # Is aggregate
    is_aggregate: bool = False

    # Aggregate functions that takes an inbox folder and returns a QuerySet of InboxFolder objects
    aggregate_func: Optional[Callable[["InboxFolder"], QuerySet["InboxFolder"]]] = None

    # Is default folder
    is_default: bool = False

    default_sources: Optional[
        list[InboxSignalSource | InboxJobSource | InboxEventSource]
    ] = None

    # The related queryset is already access-scoped by the caller.
    on_group: Optional[
        Callable[[list["InboxItem"], QuerySet["InboxItem"]], list[InboxItemGroup]]
    ] = None

    def resolve_filters(
        self, folder: "InboxFolder"
    ) -> list[InboxFolderTypeFilterDefinition]:
        """Resolve static or folder-specific filters."""
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
