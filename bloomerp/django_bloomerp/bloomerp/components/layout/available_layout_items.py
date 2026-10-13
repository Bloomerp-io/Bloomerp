

from django.http import Http404, HttpRequest, HttpResponse
from bloomerp.models.forms.form import Form

from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render

from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.services.sectioned_layout_services import get_available_layout_fields
from bloomerp.services.workspace_services import UserWorkspaceService


def _get_tiles(request: HttpRequest, content_type: ContentType):
    service = UserWorkspaceService(request.user)
    return service.get_available_workspace_tiles()


def _get_scope_from_content_type(
    request: HttpRequest,
    content_type: ContentType,
) -> str | None:
    model_cls = content_type.model_class()
    if model_cls is Form:
        return "create"
    if model_cls is UserObjectLayoutPreference:
        scope = request.GET.get("layout_mode", "detail")
        return scope if scope in {"create", "detail"} else None
    return None


def _get_application_fields(request: HttpRequest, content_type: ContentType):
    manager = UserPolicyManager(request.user)
    scope = _get_scope_from_content_type(request, content_type)
    if scope is None:
        return HttpResponse("Unsupported content type for application fields", status=400)

    agent_id = request.GET.get("target_content_type_id") or request.GET.get(
        "content_type_id"
    )
    if not agent_id:
        return HttpResponse("Missing target_content_type_id", status=400)

    model_content_type = get_object_or_404(ContentType, id=agent_id)
    model = model_content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    permission = create_permission_str(model, "add" if scope == "create" else "view")
    if not manager.has_global_permission(model, permission):
        return HttpResponse("Permission denied", status=403)

    return get_available_layout_fields(
        content_type=model_content_type,
        user=request.user,
        layout_kind=scope,
    )


CALLABLES = {
    Workspace: _get_tiles,
    Form: _get_application_fields,
    UserObjectLayoutPreference: _get_application_fields,
}


@router.register(
    path="components/layout/available-items/<int:content_type_id>/",
    name="components_available_layout_items"
)
def available_layout_items(
    request: HttpRequest,
    content_type_id: int,
) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    content_type: ContentType = get_object_or_404(ContentType, id=content_type_id)

    func = CALLABLES.get(content_type.model_class())
    if not func:
        raise Http404()

    items = func(request, content_type)

    if isinstance(items, HttpResponse):
        return items

    return render(
        request,
        "components/layout/available_items.html",
        {"items": items},
    )
