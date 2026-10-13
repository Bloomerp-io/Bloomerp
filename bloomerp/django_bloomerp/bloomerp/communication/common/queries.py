"""Common local inbox queries."""

from typing import TYPE_CHECKING
from django.db.models import Q, QuerySet
from bloomerp.utils.requests import parse_bool_parameter
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.parser import deserialize_filters

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def apply_inbox_filters(
    queryset: QuerySet["InboxItem"],
    query_params: dict[str, str] | None,
) -> QuerySet["InboxItem"]:
    """Narrow a scoped inbox queryset using serialized shared filter conditions."""
    from bloomerp.models.communication.inbox.inbox_item import InboxItem

    serialized_filters = (query_params or {}).get("filter")
    filters = (
        deserialize_filters(serialized_filters)
        if serialized_filters is not None
        else []
    )
    return ModelFilterManager(InboxItem).apply(filters, queryset=queryset)


def on_query_default(
    filters: dict[str, str] | None, folder: "InboxFolder", _: bool
) -> QuerySet["InboxItem"]:
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
    queryset = apply_inbox_filters(queryset, filters)
    filters.pop("filter", None)
    search_query = filters.pop("q", None)

    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query) | Q(snippet__icontains=search_query)
        )

    return queryset.order_by("-datetime_received", "-datetime_created").filter(
        **filters
    )


def on_query_all(
    filters: dict[str, str] | None, folder: "InboxFolder", _: bool
) -> QuerySet["InboxItem"]:
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

    return (
        apply_inbox_filters(queryset, filters)
        .distinct()
        .order_by("-datetime_received", "-datetime_created")
    )
