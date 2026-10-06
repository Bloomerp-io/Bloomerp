"""Searchable document templates for every rich-text editor."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from bloomerp.router import router
from bloomerp.services.document_template_selection import readable_document_templates


@router.register(path="components/text_editor/templates", url_name="components_text_editor_templates")
@login_required
@require_GET
def text_editor_templates(request: HttpRequest) -> JsonResponse:
    """Return template copies and metadata without restricting their content types."""
    query = request.GET.get("q", "").strip()[:200]
    templates = readable_document_templates(request.user, query)
    return JsonResponse({"templates": [
        {"id": str(template.pk), "name": template.name, "body": template.template or ""}
        for template in templates[:20]
    ]})
