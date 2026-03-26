from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import get_available_layout_fields


def _get_layout_kind(request: HttpRequest) -> str:
    """Return the requested layout kind and default to detail for invalid/missing values."""
    layout_kind = request.GET.get("layout_kind", "detail")
    return layout_kind if layout_kind in {"detail", "create"} else "detail"


def _get_layout_permission(model, *, layout_kind: str) -> str:
    """Build the Django permission codename prefix used to access a layout kind."""
    permission_prefix = "add" if layout_kind == "create" else "view"
    return f"{model._meta.app_label}.{permission_prefix}_{model._meta.model_name}"


@router.register(
    path="components/workspaces/crud_layout_available_fields/",
    name="components_workspaces_crud_layout_available_fields",
)
def crud_layout_available_fields(request: HttpRequest) -> HttpResponse:
    """Renders the available layout fields for either detail or create CRUD layouts."""
    content_type_id = request.GET.get("content_type_id")
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)

    layout_kind = _get_layout_kind(request)
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    if not request.user.has_perm(_get_layout_permission(model, layout_kind=layout_kind)):
        return HttpResponse("Permission denied", status=403)

    return render(
        request,
        "components/layouts/available_items.html",
        {"items": get_available_layout_fields(content_type=content_type, user=request.user, layout_kind=layout_kind)},
    )
