from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.sectioned_layout_services import get_available_layout_fields


def _get_legacy_layout_kind(request: HttpRequest) -> str:
    layout_kind = request.GET.get("layout_kind", "detail")
    return layout_kind if layout_kind in {"detail", "create"} else "detail"


def _render_available_fields(request: HttpRequest, *, scope: str) -> HttpResponse:
    content_type_id = request.GET.get("content_type_id")
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    permission = create_permission_str(model, "add" if scope == "create" else "view")
    if not request.user.has_perm(f"{model._meta.app_label}.{permission}"):
        return HttpResponse("Permission denied", status=403)

    if scope == "create":
        items = [
            {
                "id": field.pk,
                "title": field.title,
                "description": field.get_field_type_enum().value.display_name,
                "icon": field.get_field_type_enum().value.icon,
            }
            for field in get_addable_fields(content_type=content_type, user=request.user)
        ]
    else:
        items = get_available_layout_fields(
            content_type=content_type,
            user=request.user,
            layout_kind="detail",
        )

    return render(
        request,
        "components/layouts/available_items.html",
        {"items": items},
    )


@router.register(
    path="components/workspaces/crud_layout_available_fields/",
    name="components_workspaces_crud_layout_available_fields",
)
def crud_layout_available_fields(request: HttpRequest) -> HttpResponse:
    return _render_available_fields(request, scope=_get_legacy_layout_kind(request))


@router.register(
    path="components/workspaces/create_layout_available_fields/",
    name="components_workspaces_create_layout_available_fields",
)
def create_layout_available_fields(request: HttpRequest) -> HttpResponse:
    return _render_available_fields(request, scope="create")


@router.register(
    path="components/workspaces/detail_layout_available_fields/",
    name="components_workspaces_detail_layout_available_fields",
)
def detail_layout_available_fields(request: HttpRequest) -> HttpResponse:
    return _render_available_fields(request, scope="detail")
