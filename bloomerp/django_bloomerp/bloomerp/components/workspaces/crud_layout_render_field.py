from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.services.sectioned_layout_services import build_create_field_context, build_detail_value_context


def _get_layout_kind(request: HttpRequest) -> str | None:
    """Read the CRUD layout kind from query params."""
    layout_kind = request.GET.get("layout_kind")
    if layout_kind in {"detail", "create"}:
        return layout_kind
    return None


@router.register(
    path="components/workspaces/crud_layout_render_field/",
    name="components_workspaces_crud_layout_render_field",
)
def crud_layout_render_field(request: HttpRequest) -> HttpResponse:
    """Render a single field fragment for either a detail or create CRUD layout."""
    content_type_id = request.GET.get("content_type_id")
    field_id = request.GET.get("field_id")
    layout_kind = _get_layout_kind(request)
    if not content_type_id or not field_id:
        return HttpResponse("Missing render parameters", status=400)
    if layout_kind is None:
        return HttpResponse("Missing or invalid layout_kind", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    application_field = get_object_or_404(ApplicationField, pk=field_id, content_type=content_type)
    context = _build_render_context(
        request=request,
        content_type=content_type,
        model=model,
        application_field=application_field,
        layout_kind=layout_kind,
    )
    if isinstance(context, HttpResponse):
        return context

    context["colspan"] = request.GET.get("colspan", 1)
    template_name = "inclusion_tags/create_view_field.html" if layout_kind == "create" else "inclusion_tags/detail_view_value.html"
    return render(request, template_name, context)


def _build_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField, layout_kind: str):
    """Build the field fragment context for a CRUD layout kind."""
    if layout_kind == "create":
        return _build_create_render_context(
            request=request,
            content_type=content_type,
            model=model,
            application_field=application_field,
        )
    return _build_detail_render_context(
        request=request,
        content_type=content_type,
        model=model,
        application_field=application_field,
    )


def _build_create_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField):
    """Render context for a create layout field fragment with addable-field filtering."""
    if not request.user.has_perm(f"{model._meta.app_label}.add_{model._meta.model_name}"):
        return HttpResponse("Permission denied", status=403)

    addable_fields = list(get_addable_fields(content_type=content_type, user=request.user))
    allowed_field_names = [field.field for field in addable_fields]
    if application_field.field not in allowed_field_names:
        return HttpResponse("Permission denied", status=403)

    form_class = bloomerp_modelform_factory(model_cls=model, fields=allowed_field_names)
    form = form_class()
    if application_field.field not in form.fields:
        return HttpResponse("Unknown field", status=400)

    return build_create_field_context(
        form=form,
        application_field=application_field,
    )


def _build_detail_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField):
    """Render context for a detail layout field fragment with row and field permissions applied."""
    object_id = request.GET.get("object_id")
    if not object_id:
        return HttpResponse("Missing object_id", status=400)

    permission_manager = UserPermissionManager(request.user)
    view_permission = f"view_{model._meta.model_name}"
    allowed_queryset = permission_manager.get_queryset(model, view_permission)
    obj = get_object_or_404(allowed_queryset, pk=object_id)

    return build_detail_value_context(
        obj=obj,
        application_field=application_field,
        can_edit=permission_manager.has_field_permission(application_field, f"change_{model._meta.model_name}"),
    )
