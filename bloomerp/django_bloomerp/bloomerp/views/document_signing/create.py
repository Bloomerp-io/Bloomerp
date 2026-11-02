"""Choose a signing source through the shared model-create wizard."""

from __future__ import annotations

import base64
import json
import logging
from hashlib import sha256
from typing import Any
from uuid import uuid4

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, QueryDict
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.document_signing.access import (
    can_create_request,
    can_generate_signing_template,
)
from bloomerp.files.access import FileAccessManager
from bloomerp.forms.document_signing.create_signature_request import (
    SignatureRequestDocumentChoiceField,
    SignatureRequestDocumentForm,
    SignatureRequestSourceForm,
)
from bloomerp.forms.document_templates import DocumentTemplateForm
from bloomerp.models.document_signing import SignatureRequest
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.document_services import DocumentTemplateService
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.signing_wizard_mixin import SigningWizardMixin
from bloomerp.views.mixins.wizard_mixin import (
    BaseStateOrchestrator,
    WizardError,
    WizardStep,
)

logger = logging.getLogger(__name__)


def source_context(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Restore the selected starting point when navigating back to the first step."""
    return {"selected_source": orchestrator.get_session_data("source") or ""}


def process_source(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Validate the starting point and discard document selections from another branch."""
    form = SignatureRequestSourceForm(data=request.POST)
    if not form.is_valid():
        return WizardError(message=_("Choose a starting point."), step=0)
    source = form.cleaned_data["source"]
    if source != orchestrator.get_session_data("source"):
        view.clear_document()
    orchestrator.set_session_data("source", source)
    return None


def document_context(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Render the branch's document picker with local validation and saved selection."""
    return {
        "form": view.document_form or view.build_document_form(),
    }


def process_document(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Store only an authorized document identifier without creating a signing request."""
    view.document_form = view.build_document_form(data=request.POST)
    if not view.document_form.is_valid():
        return WizardError(message=_("Choose an available document."), step=1)
    identity = str(view.document_form.cleaned_data["document"].pk)
    if identity != orchestrator.get_session_data("document_id"):
        view.clear_document()
    orchestrator.set_session_data("document_id", identity)
    return None


def generator_context(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Embed the existing generator layout with restored variables and a saved PDF preview."""
    saved_data = QueryDict(mutable=True)
    for name, values in (
        orchestrator.get_session_data("generation_config") or {}
    ).items():
        saved_data.setlist(name, values)
    file = None
    if orchestrator.get_session_data("generated_file_id"):
        file = view.get_signing_file()
    template = view.get_selected_document()
    files = (
        FileAccessManager(request.user)
        .get_queryset(DocumentTemplateService(template, request.user).get_files())
        .order_by("-datetime_created")
    )
    return {
        "form": view.generator_form
        or view.build_generator_form(data=saved_data or None),
        "generator_embedded": True,
        "allow_persist": False,
        "file_bytes": view.preview_pdf,
        "generated_file": file,
        "files": files,
    }


def process_generator(
    request: HttpRequest,
    view: CreateSignatureRequestView,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Preview without saving, or create one reusable PDF when advancing to preparation."""
    view.generator_form = view.build_generator_form(data=request.POST)
    if not view.generator_form.is_valid():
        return WizardError(message=_("Review the highlighted fields."), step=2)
    config = {name: request.POST.getlist(name) for name in view.generator_form.fields}
    if config != orchestrator.get_session_data("generation_config"):
        view.clear_signing_preparation()
        orchestrator.set_session_data("generated_file_id", None)
    orchestrator.set_session_data("generation_config", config)
    template = view.get_selected_document()
    generation_key = sha256(
        json.dumps(
            {
                "wizard": orchestrator.get_session_data("generation_id"),
                "template": str(template.pk),
                "revision": template.datetime_updated.isoformat(),
                "config": config,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    created_file = None
    try:
        if request.POST.get("_wizard_action") == "preview":
            pdf_bytes = DocumentTemplateService(template, request.user).generate(
                view.generator_form
            )
            view.preview_pdf = base64.b64encode(pdf_bytes).decode("ascii")
            return None
        # Lock the template so concurrent retries find the first committed file.
        with transaction.atomic():
            template = DocumentTemplate.objects.select_for_update().get(pk=template.pk)
            file = FileNode.objects.filter(
                created_by=request.user, meta__signing_generation=generation_key
            ).first()
            if file is None:
                service = DocumentTemplateService(template, request.user)
                created_file = file = service.create_file(
                    service.generate(view.generator_form),
                    objects=view.generator_form.objects,
                )
                file.meta["signing_generation"] = generation_key
                file.save(update_fields=["meta"])
    except Exception:
        if created_file is not None:
            created_file.content.delete(save=False)
        logger.exception("Could not generate signing PDF from template %s", template.pk)
        return WizardError(
            message=_(
                "The document could not be generated. Review the inputs and try again."
            ),
            step=2,
        )
    if str(file.pk) != orchestrator.get_session_data("generated_file_id"):
        view.clear_signing_preparation()
    orchestrator.set_session_data("generation_config", config)
    orchestrator.set_session_data("generated_file_id", str(file.pk))
    return None


@router.register(
    path="create",
    route_type="model",
    models=SignatureRequest,
    name="Create {model}",
    url_name="add",
    override=True,
    description="Create a signature request",
)
class CreateSignatureRequestView(SigningWizardMixin, BaseBloomerpView, TemplateView):
    """Compose source selection and optional generation with the reusable signing steps."""

    model = SignatureRequest
    session_key = "signature_request_create_wizard"
    document_form: SignatureRequestDocumentForm | None = None
    generator_form: DocumentTemplateForm | None = None
    preview_pdf: str | None = None

    def has_permission(self) -> bool:
        """Require the shared creation capability on every wizard request."""
        return can_create_request(UserPolicyManager(self.request.user))

    def normalize_step_index(self, step: int) -> int:
        """Require a selected source and generated PDF before entering the signing flow."""
        if self.orchestrator.get_session_data("source") not in {"file", "template"}:
            return 0
        if not self.orchestrator.get_session_data("document_id"):
            return min(step, 1)
        if self.orchestrator.get_session_data(
            "source"
        ) == "template" and not self.orchestrator.get_session_data("generated_file_id"):
            return min(step, 2)
        return super().normalize_step_index(step)

    def clear_document(self) -> None:
        """Invalidate generation and preparation whenever the selected source changes."""
        self.clear_signing_preparation()
        for key in ("document_id", "generated_file_id", "generation_config"):
            self.orchestrator.set_session_data(key, None)
        self.orchestrator.set_session_data("generation_id", str(uuid4()))

    def get_signing_step_offset(self) -> int:
        """Insert generation only when the selected source is a document template."""
        return 3 if self.orchestrator.get_session_data("source") == "template" else 2

    def get_signing_template_id(self) -> str | None:
        """Carry the chosen template into preparation without asking the user to select it again."""
        if self.orchestrator.get_session_data("source") == "template":
            return self.orchestrator.get_session_data("document_id")
        return None

    def get_selected_document(self) -> FileNode | DocumentTemplate:
        """Revalidate the source record against the same queryset as the document picker."""
        form = self.build_document_form(
            data={"document": self.orchestrator.get_session_data("document_id")}
        )
        if not form.is_valid():
            raise PermissionDenied("The selected document is no longer available.")
        return form.cleaned_data["document"]

    def get_signing_file(self) -> FileNode:
        """Resolve the selected PDF or this template's currently readable generated output."""
        document = self.get_selected_document()
        if isinstance(document, FileNode):
            return document
        return get_object_or_404(
            FileAccessManager(self.request.user).get_queryset(
                FileNode.objects.filter(
                    meta__extension="pdf",
                    references__content_type__model="documenttemplate",
                    references__content_type__app_label="bloomerp",
                    references__object_id=str(document.pk),
                )
            ),
            pk=self.orchestrator.get_session_data("generated_file_id"),
        )

    def build_generator_form(self, data: Any = None) -> DocumentTemplateForm:
        """Reuse generator fields, scope source records, and always persist signing PDFs."""
        template = self.get_selected_document()
        manager = UserPolicyManager(self.request.user)
        if not isinstance(
            template, DocumentTemplate
        ) or not can_generate_signing_template(template, manager):
            raise PermissionDenied("You cannot generate this document template.")
        if not self.orchestrator.get_session_data("generation_id"):
            self.orchestrator.set_session_data("generation_id", str(uuid4()))
        form = DocumentTemplateService(template, self.request.user).get_form()(
            data=data, allow_persist=False
        )
        for name, field in list(form.fields.items()):
            if isinstance(field, forms.ModelChoiceField):
                model = field.queryset.model
                queryset = (
                    manager.get_accessible_queryset(model, "view")
                    if manager.has_global_permission(model, "view")
                    else model.objects.none()
                )
                form.fields[name] = SignatureRequestDocumentChoiceField(
                    queryset=queryset,
                    widget=field.widget,
                    label=field.label,
                    help_text=field.help_text,
                    required=field.required,
                    initial=field.initial,
                    empty_label=field.empty_label,
                    to_field_name=field.to_field_name,
                )
        return form

    def build_document_form(self, data: Any = None) -> SignatureRequestDocumentForm:
        """Resolve the branch from session state and reapply current read permissions."""
        return SignatureRequestDocumentForm(
            data=data,
            user=self.request.user,
            source=self.orchestrator.get_session_data("source"),
            initial={"document": self.orchestrator.get_session_data("document_id")},
        )

    def get_step(self, step: int) -> WizardStep | None:
        """Prefix the shared signing steps with selection and optional PDF generation."""
        if step == 0:
            return WizardStep(
                name=_("Starting point"),
                description=_("Start from an existing file or a document template."),
                template_name="views/document_signing/create/source.html",
                context_func=source_context,
                process_func=process_source,
            )
        if step == 1:
            from_file = self.orchestrator.get_session_data("source") == "file"
            return WizardStep(
                name=_("Select a file")
                if from_file
                else _("Select a document template"),
                description=_("Choose the PDF you want to prepare for signing.")
                if from_file
                else _("Choose the template you want to generate a document from."),
                template_name="views/document_signing/create/document.html",
                context_func=document_context,
                process_func=process_document,
            )
        if step == 2 and self.orchestrator.get_session_data("source") == "template":
            return WizardStep(
                name=_("Generate document"),
                template_name="components/document_templates/generate_document_template.html",
                context_func=generator_context,
                process_func=process_generator,
                include_padding=False,
            )
        return super().get_step(step)

    def should_advance_after_process(self, step: int) -> bool:
        """Keep preview submissions on the generator step without changing normal navigation."""
        return not (
            step == 2
            and self.orchestrator.get_session_data("source") == "template"
            and self.request.POST.get("_wizard_action") == "preview"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Make the generation action explicit within the composed wizard."""
        context = super().get_context_data(**kwargs)
        if (
            context["step_index"] == 2
            and self.orchestrator.get_session_data("source") == "template"
        ):
            context["wizard_submit_label"] = _("Generate and continue")
        return context
