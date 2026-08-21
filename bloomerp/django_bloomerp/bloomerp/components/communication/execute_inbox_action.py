from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from bloomerp.communication.inbox_folder_definition import InboxActionDefinition
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.communication.utils.permissions import (
    accessible_inbox_folders,
    accessible_inbox_items,
    manageable_inboxes,
)
from bloomerp.router import router
from bloomerp.utils.requests import render_message


@router.register(
    path="components/communication/execute_inbox_action/<str:level>/<str:item_id>/<str:action_key>",
    url_name="components_execute_inbox_action",
)
@login_required
def execute_inbox_action(request: HttpRequest, level: str, item_id: str, action_key: str) -> HttpResponse:
    if level not in ["item", "folder"]:
        return render_message(request, "Unknown inbox action level.", "error")

    try:
        if level == "folder":
            action_target = get_object_or_404(
                accessible_inbox_folders(request.user),
                id=item_id,
            )
            action = _get_folder_action(action_target, action_key)
            if (
                action.key == "delete_inbox_folder"
                and not manageable_inboxes(request.user)
                .filter(pk=action_target.inbox_id)
                .exists()
            ):
                return HttpResponse(
                    "Only the inbox owner can delete folders.",
                    status=403,
                )
        else:
            action_target = get_object_or_404(
                accessible_inbox_items(request.user),
                id=item_id,
            )
            action = _get_item_action(action_target, action_key)

        if request.method.lower() != action.http_method:
            return HttpResponse(status=405)

        return action.execution_func(request, action_target)
    except ValidationError as exc:
        return render_message(request, "; ".join(exc.messages), "error")


def _get_folder_action(folder: InboxFolder, action_key: str) -> InboxActionDefinition:
    for action in folder.inbox_folder_type().actions or []:
        if action.key == action_key and action.is_available_for(folder):
            return action
    raise ValidationError("This action is not available for the selected folder.")


def _get_item_action(item: InboxItem, action_key: str) -> InboxActionDefinition:
    for action in item.get_inbox_item_type().actions or []:
        if action.key == action_key and action.is_available_for(item):
            return action
    raise ValidationError("This action is not available for the selected inbox item.")
