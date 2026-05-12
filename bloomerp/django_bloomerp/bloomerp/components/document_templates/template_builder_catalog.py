import json
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.router import router
from bloomerp.services.document_services import DocumentTemplateService
from bloomerp.views.document_templates.document_template_builder_view import (
    get_template_content_types,
    parse_free_variables_json,
)


def _parse_payload(request: HttpRequest) -> dict[str, Any]:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


@router.register(
    path="components/document-template-builder/catalog/",
    name="components_document_template_builder_catalog",
)
@require_POST
def document_template_builder_catalog(request: HttpRequest) -> JsonResponse:
    payload = _parse_payload(request)
    raw_content_type_ids = payload.get("content_type_ids") or []
    if not isinstance(raw_content_type_ids, list):
        raw_content_type_ids = []

    content_type_ids: list[int] = []
    for raw_id in raw_content_type_ids:
        try:
            content_type_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    content_types = list(
        get_template_content_types()
        .filter(pk__in=content_type_ids)
        .order_by("app_label", "model")
    )

    template = DocumentTemplate(
        free_variables=parse_free_variables_json(str(payload.get("free_variables_json") or "[]")),
        template=str(payload.get("template_content") or ""),
    )
    template._unsaved_content_types = content_types

    return JsonResponse(DocumentTemplateService(template, request.user).build_variable_catalog())
