"""Reusable read-state filters."""

from bloomerp.communication.definition import InboxFolderTypeFilterDefinition
from bloomerp.filters.definition import Filter, FilterCondition

# Define common filters
IS_READ_FILTER = InboxFolderTypeFilterDefinition(
    key="is_read",
    name="Read",
    filters=[
        Filter(
            connector="AND",
            conditions=[
                FilterCondition(field_path="is_read", lookup_id="equals", value=True)
            ],
        )
    ],
)
UNREAD_FILTER = InboxFolderTypeFilterDefinition(
    key="unread",
    name="Unread",
    filters=[
        Filter(
            connector="AND",
            conditions=[
                FilterCondition(field_path="is_read", lookup_id="equals", value=False)
            ],
        )
    ],
)
