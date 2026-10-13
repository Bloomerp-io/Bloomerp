"""Aggregate inbox folder definition."""

from bloomerp.communication.common.grouping import group_inbox_items
from bloomerp.communication.definition import InboxFolderTypeDefinition
from bloomerp.communication.common.actions import (
    MARK_ALL_AS_READ_ACTION,
    DELETE_INBOX_FOLDER_ACTION,
)
from bloomerp.communication.common.queries import on_query_all

ALL = InboxFolderTypeDefinition(
    key="all",
    name="All",
    description="All inbox items across all folders",
    icon="fa fa-inbox",
    actions=[MARK_ALL_AS_READ_ACTION, DELETE_INBOX_FOLDER_ACTION],
    on_query=on_query_all,
    on_group=group_inbox_items,
    is_aggregate=True,
    is_default=True,
)
