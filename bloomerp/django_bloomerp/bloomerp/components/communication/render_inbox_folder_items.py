from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.communication.utils.permissions import accessible_inbox_folders, accessible_inbox_items
from bloomerp.communication.definition import InboxItemGroup
from bloomerp.router import router

INBOX_PAGE_SIZE = 100


@router.register(
    path="components/communication/render_inbox_folder/<str:folder_id>/",
    url_name="components_render_inbox_folder_items"
)
@login_required
def render_inbox_folder(request: HttpRequest, folder_id: str) -> HttpResponse:
    """
    Renders the inbox items for a given user and inbox type.

    Args:
        request (HttpRequest): The HTTP request object containing GET parameters.
    """
    inbox_folder = get_object_or_404(
        accessible_inbox_folders(request.user),
        id=folder_id,
    )
    error_message = None
    page_obj = None

    query_params = request.GET.dict()
    query_params.pop("page", None)
    try:
        paginator = Paginator(
            inbox_folder.query_items(query_params),
            INBOX_PAGE_SIZE,
        )
        page_obj = paginator.get_page(request.GET.get("page", 1))
        items = page_obj.object_list
    except ValidationError as exc:
        items = []
        error_message = "; ".join(exc.messages)

    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)

    items = list(items)
    grouping = inbox_folder.inbox_folder_type().on_group
    groups = grouping(items, accessible_inbox_items(request.user)) if grouping else [
        InboxItemGroup(item=item, related_items=[], key=str(item.pk)) for item in items
    ]

    return render(
        request,
        "components/communication/render_inbox_folder_items.html",
        {
            "items": items,
            "groups": groups,
            "inbox_folder": inbox_folder,
            "error_message": error_message,
            "page_obj": page_obj,
            "pagination_querystring": pagination_params.urlencode(),
        }
    )
