from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_http_methods
from django_cotton import render_component

from bloomerp.router import router
from bloomerp.services.document_services import FIELD_TYPE_TEMPLATE_INJECTIONS, DocumentTemplateService
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.document_templates.document_template_builder_view import (
    get_template_content_types,
)


@router.register(
    path="components/document-template-builder/catalog/",
    name="components_document_template_builder_catalog",
)
@require_http_methods(["GET"])
def document_template_builder_catalog(request: HttpRequest) -> HttpResponse:
    content_type_ids = request.GET.getlist("content_types")

    content_types = list(
        get_template_content_types()
        .filter(pk__in=content_type_ids)
        .order_by("app_label", "model")
    )

    # Get the permission manager
    manager = UserPermissionManager(request.user)
    service = DocumentTemplateService(document_template=None)
    variables = []
    
    for content_type in content_types:
        root_name = service.get_content_type_variable_name(content_type)
        fields = manager.get_accessible_fields(
            content_type,
            create_permission_str(
                content_type.model_class(),
                "view"
            )
        )
        
        for field in fields:
            field_type = field.get_field_type_enum()
            variables.append({
                "content_type_label": content_type.name.title(),
                "label": field.title,
                "field_type_label": field_type.display_name,
                "icon": field_type.icon,
                "token": f"{root_name}.{field.field}",
                "injection_methods": FIELD_TYPE_TEMPLATE_INJECTIONS.get(field_type.id, []),
            })

    return HttpResponse(
        render_component(
            request,
            "features.document_templates.variable_catalog",
            {
                "variables": variables,
            },
        )
    )
