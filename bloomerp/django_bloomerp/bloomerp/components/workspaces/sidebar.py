import json
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db.models import Max
from django.http import JsonResponse
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.forms.sidebar import CreateLinkSidebarItemForm, CreateSidebarFolderForm
from bloomerp.models import Sidebar, SidebarItem
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh, render_template_and_message

SIDEBAR_CONTENT_TEMPLATE = "components/sidebar/content.html"
SIDEBAR_SELECT_ITEMS_TEMPLATE = "components/sidebar/select_sidebar_items.html"


def _get_item_id_from_request(request: HttpRequest, key: str) -> str | None:
    if request.method == "GET":
        return request.GET.get(key)
    if request.method == "POST":
        return request.POST.get(key)
    return None


def _get_parent_item(request: HttpRequest, sidebar: Sidebar, key: str = "parent_item_id") -> SidebarItem | None:
    raw_parent_item_id = _get_item_id_from_request(request, key)
    if not raw_parent_item_id:
        return None

    return get_object_or_404(
        SidebarItem,
        pk=raw_parent_item_id,
        sidebar=sidebar,
        is_folder=True,
    )


def _get_drop_position(request: HttpRequest) -> int:
    raw_position = (_get_item_id_from_request(request, "position") or "").strip()
    if raw_position == "":
        raise ValueError("A target position is required.")

    try:
        position = int(raw_position)
    except ValueError as exc:
        raise ValueError("Target position must be a whole number.") from exc

    if position < 0:
        raise ValueError("Target position cannot be negative.")

    return position


def _validation_error_message(error: ValidationError | Exception) -> str:
    if isinstance(error, ValidationError):
        if hasattr(error, "message_dict") and error.message_dict:
            first_value = next(iter(error.message_dict.values()))
            if isinstance(first_value, list) and first_value:
                return str(first_value[0])
            return str(first_value)
        if error.messages:
            return str(error.messages[0])
    return str(error)


def _derive_link_name_from_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if hostname:
        host_label = hostname.removeprefix("www.").split(".")[0]
        if host_label:
            return " ".join(segment.capitalize() for segment in host_label.replace("_", " ").replace("-", " ").split())

    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts:
        return " ".join(segment.capitalize() for segment in path_parts[-1].replace("_", " ").replace("-", " ").split())

    return _("New link")


def _get_sidebar_item_form_class(is_folder: bool):
    return CreateSidebarFolderForm if is_folder else CreateLinkSidebarItemForm


def _render_sidebar_item_form(
    request: HttpRequest,
    *,
    form,
    url: str,
    submit_label: str,
    parent_item: SidebarItem | None = None,
) -> HttpResponse:
    hidden_args = {"parent_item_id": parent_item.id if parent_item else ""} if parent_item is not None else {}
    return render_blank_form(
        request,
        form,
        hidden_args,
        url,
        submit_label,
    )


def _render_sidebar_success_response(request: HttpRequest, sidebar: Sidebar, message: str) -> HttpResponse:
    response = render_template_and_message(
        request,
        message=message,
        type="success",
        template_name=SIDEBAR_CONTENT_TEMPLATE,
        context={"sidebar": sidebar},
        hx_swap_oob="outerHTML",
        hx_swap_oob_id="sidebar-content",
    )
    response["HX-Trigger"] = json.dumps({"dropdown-close": True})
    return response

@router.register(
    path="components/workspaces/sidebar/select/<int:sidebar_id>/",
    name="components_workspaces_sidebar_set_selected",
)
def sidebar_set_selected(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    """
    Component to select a particular 
    """
    
    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user)
    sidebar.select()

    return render(
        request,
        SIDEBAR_CONTENT_TEMPLATE,
        {
            "sidebar": sidebar,
        },
    )


@router.register(
    path="components/workspaces/sidebar/select/",
    name="components_workspaces_sidebar_select_menu",
)
def sidebar_select_menu(request: HttpRequest) -> HttpResponse:
    sidebar = request.user.selected_sidebar
    sidebars = request.user.sidebars.order_by("name", "id")

    return render(
        request,
        SIDEBAR_SELECT_ITEMS_TEMPLATE,
        {
            "sidebar": sidebar,
            "sidebars": sidebars,
        },
    )


@router.register(
    path="components/workspaces/sidebar/create/",
    name="components_workspaces_sidebar_create",
)
def sidebar_create(request: HttpRequest) -> HttpResponse:
    """
    Component to create a new sidebar. Only accepts POST as it's only a single action with a simple field (i.e. name).
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Sidebar name is required", status=400)

    sidebar = Sidebar.objects.create(
        user=request.user,
        name=name,
        selected=False,
    )
    sidebar.select()

    response = render_template_and_message(
        request,
        "Sidebar created",
        "success",
        SIDEBAR_CONTENT_TEMPLATE,
        {
            "sidebar": sidebar,
        },
    )
    response["HX-Trigger"] = json.dumps({"dropdown-close": True})
    return response


@router.register(
    path="components/workspaces/sidebar/delete/<int:sidebar_id>/",
    name="components_workspaces_sidebar_delete",
)
def sidebar_delete(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user)
    remaining_sidebars = request.user.sidebars.exclude(pk=sidebar.pk).order_by("id")

    if not remaining_sidebars.exists():
        return HttpResponse("At least one sidebar is required", status=400)

    sidebar.delete()
    next_sidebar = remaining_sidebars.first()
    next_sidebar.select()

    return render_page_refresh()


@router.register(
    path="components/workspaces/sidebar/<int:sidebar_id>/folders/create/",
    name="components_workspaces_sidebar_create_folder",
)
def sidebar_create_folder(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    """
    Component to create a folder in the selected sidebar.
    """
    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user)
    parent_item = _get_parent_item(request, sidebar)
    url = reverse("components_workspaces_sidebar_create_folder", kwargs={"sidebar_id": sidebar_id})
    if sidebar.user != request.user:
        return HttpResponse("Unauthorized", status=401)
    
    match request.method:
        case "GET":
            return _render_sidebar_item_form(
                request,
                form=CreateSidebarFolderForm(),
                parent_item=parent_item,
                url=url,
                submit_label=_("Add"),
            )
        case "POST":
            form = CreateSidebarFolderForm(request.POST)
            if not form.is_valid():
                return _render_sidebar_item_form(
                    request,
                    form=form,
                    parent_item=parent_item,
                    url=url,
                    submit_label=_("Add"),
                )

            next_position = (
                SidebarItem.objects.filter(sidebar=sidebar, parent=parent_item).aggregate(max_position=Max("position"))["max_position"]
            )
            SidebarItem.create_folder(
                sidebar=sidebar,
                name=form.cleaned_data["name"],
                icon=form.cleaned_data["icon"],
                parent=parent_item,
                position=0 if next_position is None else next_position + 1,
            )

            return _render_sidebar_success_response(request, sidebar, _("Folder created"))
        case _:
            return HttpResponse("Method not allowed", status=405)


@router.register(
    path="components/workspaces/sidebar/<int:sidebar_id>/links/create/",
    name="components_workspaces_sidebar_create_link",
)
def sidebar_create_link(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    """
    Component to create a link in the selected sidebar.
    """
    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user) # Handles permission stuff
    parent_item = _get_parent_item(request, sidebar)
    url = reverse("components_workspaces_sidebar_create_link", kwargs={"sidebar_id": sidebar_id})
    
    match request.method:
        case "GET":
            return _render_sidebar_item_form(
                request,
                form=CreateLinkSidebarItemForm(),
                parent_item=parent_item,
                url=url,
                submit_label=_("Add"),
            )
        
        case "POST":
            form = CreateLinkSidebarItemForm(
                data=request.POST
            )

            if form.is_valid():
                next_position = (
                    SidebarItem.objects.filter(sidebar=sidebar, parent=parent_item).aggregate(max_position=Max("position"))["max_position"]
                )
                SidebarItem.create_link(
                    sidebar=sidebar,
                    name=form.cleaned_data["name"],
                    url=form.cleaned_data["url"],
                    icon=form.cleaned_data["icon"],
                    parent=parent_item,
                    position=0 if next_position is None else next_position + 1,
                )

                return _render_sidebar_success_response(request, sidebar, _("Item created"))

            return _render_sidebar_item_form(
                request,
                form=form,
                parent_item=parent_item,
                url=url,
                submit_label=_("Add"),
            )
        case _:
            return HttpResponse("Method not allowed", status=405)


@router.register(
    path="components/workspaces/sidebar/items/<int:item_id>/edit/",
    name="components_workspaces_sidebar_edit_item",
)
def sidebar_edit_item(request: HttpRequest, item_id: int) -> HttpResponse:
    item = get_object_or_404(SidebarItem, pk=item_id, sidebar__user=request.user)
    form_class = _get_sidebar_item_form_class(item.is_folder)
    url = reverse("components_workspaces_sidebar_edit_item", kwargs={"item_id": item.id})

    match request.method:
        case "GET":
            return _render_sidebar_item_form(
                request,
                form=form_class(instance=item),
                url=url,
                submit_label=_("Save"),
            )
        case "POST":
            form = form_class(request.POST, instance=item)
            if not form.is_valid():
                return _render_sidebar_item_form(
                    request,
                    form=form,
                    url=url,
                    submit_label=_("Save"),
                )

            form.save()
            return _render_sidebar_success_response(request, item.sidebar, _("Item updated"))
        case _:
            return HttpResponse("Method not allowed", status=405)


@router.register(
    path="components/workspaces/sidebar/items/<int:item_id>/delete/",
    name="components_workspaces_sidebar_delete_item",
)
def sidebar_delete_item(request: HttpRequest, item_id: int) -> HttpResponse:
    """
    Component to delete a sidebar item (either a folder or a tile).
    """
    item = get_object_or_404(SidebarItem, pk=item_id, sidebar__user=request.user) # The user condition takes care of the permission
    sidebar = item.sidebar
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    item.delete()

    return render_template_and_message(
        request,
        _('Item removed'),
        "success",
        SIDEBAR_CONTENT_TEMPLATE,
        {"sidebar":sidebar}
    )


@router.register(
    path="components/workspaces/sidebar/<int:sidebar_id>/items/move/",
    name="components_workspaces_sidebar_move_item",
)
def sidebar_move_item(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user)
    item_id = (_get_item_id_from_request(request, "item_id") or "").strip()
    if not item_id:
        return JsonResponse({"ok": False, "message": _("An item is required.")}, status=400)

    item = get_object_or_404(SidebarItem, pk=item_id, sidebar=sidebar)
    parent_item = _get_parent_item(request, sidebar)

    try:
        position = _get_drop_position(request)
        item.move_to(parent_item, position)
    except (ValidationError, ValueError) as exc:
        return JsonResponse({"ok": False, "message": _validation_error_message(exc)}, status=400)

    return JsonResponse({"ok": True, "message": _("Item moved")})


@router.register(
    path="components/workspaces/sidebar/<int:sidebar_id>/links/drop/",
    name="components_workspaces_sidebar_create_link_from_drop",
)
def sidebar_create_link_from_drop(request: HttpRequest, sidebar_id: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    sidebar = get_object_or_404(Sidebar, pk=sidebar_id, user=request.user)
    parent_item = _get_parent_item(request, sidebar)
    raw_url = (request.POST.get("url") or "").strip()
    raw_name = (request.POST.get("name") or "").strip()

    if not raw_url:
        return JsonResponse({"ok": False, "message": _("A URL is required.")}, status=400)

    try:
        position = _get_drop_position(request)
        sibling_count = SidebarItem.objects.filter(sidebar=sidebar, parent=parent_item).count()
        link = SidebarItem.create_link(
            sidebar=sidebar,
            name=raw_name or _derive_link_name_from_url(raw_url),
            url=raw_url,
            parent=parent_item,
            position=sibling_count,
        )
        link.move_to(parent_item, position)
    except (ValidationError, ValueError) as exc:
        return JsonResponse({"ok": False, "message": _validation_error_message(exc)}, status=400)

    return JsonResponse({"ok": True, "message": _("Link created")})
