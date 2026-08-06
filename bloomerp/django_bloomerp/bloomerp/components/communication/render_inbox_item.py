from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from bloomerp.communication.utils.permissions import accessible_inbox_items
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.router import router

@router.register(
    path="components/communication/render_inbox_item/<str:item_id>",
    url_name="components_render_inbox_item"
)
@login_required
def render_inbox_item(request: HttpRequest, item_id: str) -> HttpResponse:
    """
    Renders a single inbox item for a given user and inbox type.

    Args:
        request (HttpRequest): The HTTP request object containing GET parameters.
        item_id (str): The ID of the inbox item to be rendered.
    """
    inbox_item = get_object_or_404(
        accessible_inbox_items(request.user),
        id=item_id,
    )
    
    inbox_item_type = inbox_item.get_inbox_item_type()
    actions = [
        action
        for action in inbox_item_type.actions or []
        if action.is_available_for(inbox_item)
    ]
    content = ""
    error_message = None
    if inbox_item_type.on_render:
        try:
            content = inbox_item_type.on_render(inbox_item, request)
            inbox_item_type.on_mark_as_read(inbox_item, request)
            
        except ValidationError as exc:
            error_message = "; ".join(exc.messages)
    
    return render(
        request,
        "components/communication/render_inbox_item.html",
        {
            "content": content,
            "error_message": error_message,
            "item": inbox_item,
            "primary_actions": [action for action in actions if action.is_primary_action],
            "secondary_actions": [action for action in actions if not action.is_primary_action],
            "notification_count":Inbox.get_unread_count_for_user(request.user)
        }
    )
