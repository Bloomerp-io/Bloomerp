from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_object_field_value,
)


@router.register(
    path="components/workspaces/crud_layout_render_field/",
    name="components_workspaces_crud_layout_render_field",
)
def crud_layout_render_field(request: HttpRequest) -> HttpResponse:
    content_type_id = request.GET.get("content_type_id")
    field_id = request.GET.get("field_id")
    if not content_type_id or not field_id:
        return HttpResponse("Missing render parameters", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    application_field = get_object_or_404(ApplicationField, pk=field_id, content_type=content_type)
    object_id = request.GET.get("object_id")
    if object_id:
        context = _build_detail_render_context(
            request=request,
            model=model,
            application_field=application_field,
            object_id=object_id,
        )
    else:
        context = _build_create_render_context(
            request=request,
            content_type=content_type,
            model=model,
            application_field=application_field,
        )

    if isinstance(context, HttpResponse):
        return context

    context["colspan"] = request.GET.get("colspan", 1)
    if "non_required_fields_visible" in request.GET:
        context["non_required_fields_visible"] = request.GET.get("non_required_fields_visible")
    return render(request, "inclusion_tags/layout_field.html", context)


def _build_create_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField):
    if not request.user.has_perm(f"{model._meta.app_label}.{create_permission_str(model, 'add')}"):
        return HttpResponse("Permission denied", status=403)

    addable_fields = list(get_addable_fields(content_type=content_type, user=request.user))
    allowed_field_names = [field.field for field in addable_fields]
    if application_field.field not in allowed_field_names:
        return HttpResponse("Permission denied", status=403)

    form_class = bloomerp_modelform_factory(model_cls=model, fields=allowed_field_names)
    form = form_class()
    if application_field.field not in form.fields:
        return HttpResponse("Unknown field", status=400)

    return build_crud_layout_field_context(
        application_field=application_field,
        bound_field=form[application_field.field],
    )


def _build_detail_render_context(*, request: HttpRequest, model, application_field: ApplicationField, object_id: str):
    permission_manager = UserPermissionManager(request.user)
    view_permission = create_permission_str(model, "view")
    allowed_queryset = permission_manager.get_queryset(model, view_permission)
    obj = get_object_or_404(allowed_queryset, pk=object_id)
    return build_crud_layout_field_context(
        application_field=application_field,
        value=get_object_field_value(obj=obj, application_field=application_field),
        can_edit=permission_manager.has_field_permission(application_field, create_permission_str(model, "change")),
    )
