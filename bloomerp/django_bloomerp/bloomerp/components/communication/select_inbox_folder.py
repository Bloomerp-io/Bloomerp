from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import format_html

from bloomerp.communication.utils.permissions import accessible_inbox_folders
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.user_inbox_preference import (
    UserInboxPreference,
)
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.communication.inbox import InboxView


@router.register(
    path="components/communication/select_inbox_folder/<str:folder_id>/",
    url_name="components_select_inbox_folder",
)
@login_required
def select_inbox_folder(
    request: HttpRequest,
    folder_id: str,
) -> HttpResponse:
    """Select an accessible folder and render only the refreshed inbox fragment."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    inbox = PreferenceManager(request.user).get_or_create_selected(
        Inbox,
        force_create=False,
    )
    if inbox is None:
        return HttpResponse("No inbox is selected.", status=400)

    folder = get_object_or_404(
        accessible_inbox_folders(request.user).filter(inbox=inbox),
        pk=folder_id,
    )
    view = InboxView()
    view.setup(request)
    subfolder_key = request.POST.get("subfolder")
    subfolder = None
    if subfolder_key:
        subfolder = next(
            (
                option
                for option in view.get_subfolder_filter_options(folder)
                if option["key"] == subfolder_key
            ),
            None,
        )
        if subfolder is None:
            return HttpResponse("Unknown inbox subfolder.", status=400)

    preference = UserInboxPreference.get_for_user(request.user)
    preference.selected_inbox_folder = folder
    preference.save(update_fields=["selected_inbox_folder"])
    context = view.get_inbox_context()
    if subfolder is not None:
        context["mailbox_filters_json"] = subfolder["filters_json"]
        context["selected_folder_label"] = format_html(
            "{} / {}", folder.name, subfolder["name"]
        )
    return render(request, "components/communication/inbox.html", context)
