"""Built-in notification folder and item definitions."""

from typing import TYPE_CHECKING
from django.db.models import QuerySet
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.communication.definition import (
    InboxFolderTypeDefinition,
    InboxItemTypeDefinition,
    InboxFolderTypeFilterDefinition,
)
from bloomerp.communication.inbox_sources import InboxEventSource, InboxSignalSource
from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage
from bloomerp.communication.common.actions import (
    MARK_ALL_AS_READ_ACTION,
    MARK_INBOX_ITEM_AS_READ_ACTION,
    DELETE_INBOX_ITEM_ACTION,
    DELETE_INBOX_FOLDER_ACTION,
)
from bloomerp.communication.common.filters import UNREAD_FILTER, IS_READ_FILTER
from bloomerp.communication.common.queries import on_query_default

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def query_notifications(
    filters: dict[str, str] | None, folder: "InboxFolder", deep: bool
) -> QuerySet["InboxItem"]:
    """Limit the common local query to notification items."""
    return on_query_default(filters, folder, deep).filter(item_type="notification")


def notification_filters(
    folder: "InboxFolder",
) -> list[InboxFolderTypeFilterDefinition]:
    """Offer read state and registered notification types."""
    return [
        UNREAD_FILTER,
        IS_READ_FILTER,
        *[
            InboxFolderTypeFilterDefinition(
                key="type_" + item.value.key,
                name=item.value.name,
                filters=[
                    Filter(
                        connector="AND",
                        conditions=[
                            FilterCondition(
                                field_path="raw_meta_data__system_message_type",
                                lookup_id="equals",
                                value=item.value.key,
                            )
                        ],
                    )
                ],
            )
            for item in SystemMessage
        ],
    ]


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
    on_query=query_notifications,
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
            folder_qs_resolver="bloomerp.communication.builtins.in_app_notifications.workflow.resolve_workflow_notification_folders",
            handler="bloomerp.communication.builtins.in_app_notifications.workflow.handle_workflow_result",
            run_async=False,
        ),
        InboxEventSource(
            key="system.message",
            folder_qs_resolver=(
                "bloomerp.communication.builtins.in_app_notifications.inbox_sources."
                "resolve_system_message_folders"
            ),
            handler=(
                "bloomerp.communication.builtins.in_app_notifications.inbox_sources."
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
                "bloomerp.communication.builtins.in_app_notifications.form_submission."
                "should_notify_form_submission"
            ),
            folder_qs_resolver=(
                "bloomerp.communication.builtins.in_app_notifications.form_submission."
                "resolve_form_submission_folders"
            ),
            handler=(
                "bloomerp.communication.builtins.in_app_notifications.form_submission."
                "handle_form_submission"
            ),
            run_async=False,
        ),
        InboxSignalSource(
            key="workflow.approval_required",
            signal="django.db.models.signals.post_save",
            sender="bloomerp.models.automation.workflow_run_step.WorkflowRunStep",
            folder_qs_resolver="bloomerp.communication.builtins.in_app_notifications.signals.workflow_approval_required.resolve",
            handler="bloomerp.communication.builtins.in_app_notifications.signals.workflow_approval_required.handle",
            predicate="bloomerp.communication.builtins.in_app_notifications.signals.workflow_approval_required.predicate",
            dispatch_uid="workflow.approval_required",
            run_async=False,
        ),
    ],
    filters=notification_filters,
)
