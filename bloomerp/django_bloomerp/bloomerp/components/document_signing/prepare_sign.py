"""Render the native PDF preparation shell; draft edits use the generated SDK."""

from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from bloomerp.document_signing.access import (
    can_prepare,
    can_save_preparation,
    can_save_signing_default,
    get_signing_document_templates,
    get_signing_layout_revisions,
)
from bloomerp.models.document_signing import (
    SignaturePreparation,
)
from bloomerp.models.document_signing.definition import SignatureFieldTypes
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/document_signing/prepare_sign/<str:file_id>",
    url_name="components_document_signing_prepare_sign",
)
@login_required
@require_GET
@ensure_csrf_cookie
def prepare_sign(request: HttpRequest, file_id: str) -> HttpResponse:
    """Prepare an authorized PDF and resume an accessible draft without writing on GET."""
    manager = UserPolicyManager(request.user)
    try:
        file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    except (ValidationError, ValueError) as error:
        raise Http404("Invalid document identifier.") from error
    if not can_prepare(file, manager):
        return HttpResponse(status=403)
    if file.metadata.extension != "pdf":
        return HttpResponse("Choose a PDF document.", status=400)

    document_templates = get_signing_document_templates(file, manager)
    selected_template = request.GET.get("document_template_id", "")
    if selected_template and selected_template not in {
        str(template.pk) for template in document_templates
    }:
        raise Http404("Document template not available for this PDF.")
    if not selected_template and len(document_templates) == 1:
        selected_template = str(document_templates[0].pk)
    template_known = (
        bool(request.GET.get("document_template_id")) or len(document_templates) == 1
    )
    drafts = manager.get_accessible_queryset(
        SignaturePreparation, BloomerpPermission.VIEW
    ).filter(original_file=file)
    draft_id = request.GET.get("preparation_id") or request.GET.get("request_id")
    if draft_id:
        try:
            draft = get_object_or_404(drafts, pk=draft_id)
        except (ValidationError, ValueError) as error:
            raise Http404("Invalid signing draft.") from error
    else:
        draft = (
            drafts.filter(created_by=request.user)
            .exclude(requests__status="draft")
            .first()
        )

    can_save = can_save_preparation(manager)
    embedded = request.GET.get("embedded") == "1"
    component_id = f"prepare-sign-{uuid4().hex}"
    context = {
        "file": file,
        "component_id": component_id,
        "config_id": f"{component_id}-config",
        "document_templates": document_templates,
        "selected_template": selected_template,
        "template_known": template_known,
        "known_template_name": next(
            (
                str(template)
                for template in document_templates
                if str(template.pk) == selected_template
            ),
            "",
        ),
        "embedded": embedded,
        "builder_config": {
            "fileId": str(file.pk),
            "fileName": file.name,
            "pdfUrl": reverse("components_preview_file", kwargs={"file_id": file.pk})
            + "?raw=1",
            "preparationId": str(draft.pk) if draft else None,
            "preparationUrl": reverse(
                "api_document_signing_preparation", kwargs={"file_id": file.pk}
            ),
            "sendUrl": reverse(
                "components_document_signing_send_signature_request",
                kwargs={"file_id": file.pk},
            ),
            "selfSignUrl": reverse(
                "components_document_signing_start_self_signing",
                kwargs={"file_id": file.pk},
            ),
            "canSave": can_save,
            "defaultLayoutUrl": reverse(
                "api_document_signing_default_layout", kwargs={"file_id": file.pk}
            ),
            "selectedDocumentTemplateId": selected_template or None,
            "documentTemplates": [
                {
                    "id": str(template.pk),
                    "name": str(template),
                    "defaultLayoutId": str(template.default_signature_layout_id)
                    if template.default_signature_layout_id
                    else None,
                    "canSave": can_save_signing_default(template, manager),
                    "revisions": [
                        {
                            "id": str(layout.pk),
                            "revision": layout.revision,
                            "is_default": layout.pk
                            == template.default_signature_layout_id,
                        }
                        for layout in get_signing_layout_revisions(template, manager)
                    ],
                }
                for template in document_templates
            ],
            "fieldTypes": [item.value.as_payload() for item in SignatureFieldTypes],
        },
    }
    return render(request, "components/document_signing/prepare_sign.html", context)
