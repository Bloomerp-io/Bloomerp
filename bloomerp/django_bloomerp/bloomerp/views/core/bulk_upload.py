from __future__ import annotations

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.forms.bulk_upload_form import BulkUploadWizardUploadForm
from bloomerp.models.files import File
from bloomerp.router import router
from bloomerp.services.bulk_services import (
    DEFAULT_REVIEW_PAGE_SIZE,
    BulkCrudService,
)
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator, WizardError, WizardMixin, WizardStep


DRAFT_FILE_ID_KEY = "file_id"
SELECTED_FIELDS_KEY = "selected_fields"
CHANGES_KEY = "changes"
REVIEW_PAGE_KEY = "review_page"
PAGE_SIZE_KEY = "page_size"
TOTAL_ROWS_KEY = "total_rows"
VALIDATION_SUMMARY_KEY = "validation_summary"


def _wizard_error_message(form) -> str:
    for error_list in form.errors.values():
        if error_list:
            return str(error_list[0])
    if form.non_field_errors():
        return str(form.non_field_errors()[0])
    return "Please review the submitted data and try again."


def ctx_upload_step(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    draft_file = view.service.get_draft_file(orchestrator.get_session_data(DRAFT_FILE_ID_KEY))
    return {
        "upload_form": getattr(view, "_upload_form", None) or BulkUploadWizardUploadForm(require_file=draft_file is None),
        "content_type_id": view.model_content_type.pk,
        "draft_file": draft_file,
        "draft_total_rows": orchestrator.get_session_data(TOTAL_ROWS_KEY) or 0,
        "wizard_submit_label": "Continue",
        "bulk_upload_success_message": view.pop_success_message(),
    }


def pcs_upload_step(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    existing_draft_file_id = orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
    existing_draft = view.service.get_draft_file(existing_draft_file_id)
    upload_form = BulkUploadWizardUploadForm(
        request.POST,
        request.FILES,
        require_file=existing_draft is None,
    )
    view._upload_form = upload_form

    if not upload_form.is_valid():
        return WizardError(
            message=_wizard_error_message(upload_form),
            title="Upload required",
            step=0,
        )

    uploaded_file = upload_form.cleaned_data.get("bulk_upload_file")
    if uploaded_file in (None, ""):
        if existing_draft is not None:
            view._upload_form = BulkUploadWizardUploadForm(require_file=False)
            return None
        return WizardError(
            message="Please select a file before continuing.",
            title="Upload required",
            step=0,
        )

    draft = view.service.create_draft(
        uploaded_file,
        previous_file_id=existing_draft_file_id,
    )
    orchestrator.set_session_data(DRAFT_FILE_ID_KEY, draft.file_id)
    orchestrator.set_session_data(SELECTED_FIELDS_KEY, draft.selected_fields)
    orchestrator.set_session_data(CHANGES_KEY, {})
    orchestrator.set_session_data(REVIEW_PAGE_KEY, 1)
    orchestrator.set_session_data(PAGE_SIZE_KEY, DEFAULT_REVIEW_PAGE_SIZE)
    orchestrator.set_session_data(TOTAL_ROWS_KEY, draft.total_rows)
    orchestrator.set_session_data(VALIDATION_SUMMARY_KEY, None)
    view._upload_form = BulkUploadWizardUploadForm(require_file=False)


def ctx_review_step(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    file_id = orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
    if not file_id:
        return {}

    review_page = getattr(view, "_review_page", None)
    if review_page is None:
        review_page = view.service.build_review_page(
            file_id=file_id,
            changes=orchestrator.get_session_data(CHANGES_KEY) or {},
            page=view.get_review_page_number(),
            page_size=view.get_review_page_size(),
        )

    return {
        "review_page": review_page,
        "selected_fields": orchestrator.get_session_data(SELECTED_FIELDS_KEY) or [],
        "wizard_submit_label": "Continue",
    }


def pcs_review_step(request: HttpRequest, view:"BloomerpBulkUploadView", orchestrator: BaseStateOrchestrator):
    file_id = orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
    if not file_id:
        return WizardError(
            message="Upload a file before continuing to review.",
            title="Draft required",
            step=0,
        )

    current_page = view.get_review_page_number()
    review_page = view.service.build_review_page(
        file_id=file_id,
        changes=orchestrator.get_session_data(CHANGES_KEY) or {},
        page=current_page,
        page_size=view.get_review_page_size(),
        data=request.POST,
    )
    view._review_page = review_page

    if not review_page.formset.is_valid():
        review_page.page_row_errors = {}
        review_page.invalid_row_indexes = []
        for form in review_page.formset.forms:
            if not form.errors and not form.non_field_errors():
                continue
            try:
                row_index = int(form["row_index"].value())
            except (TypeError, ValueError):
                continue
            review_page.page_row_errors[row_index] = view.service.serialize_form_errors(form.errors)
            non_field_errors = [str(error) for error in form.non_field_errors()]
            if non_field_errors:
                review_page.page_row_errors[row_index]["__all__"] = non_field_errors
            review_page.invalid_row_indexes.append(str(row_index))
        return WizardError(
            message="Please fix the highlighted row errors before continuing.",
            title="Review errors",
            step=1,
        )

    merged_changes = view.service.merge_page_changes(
        file_id=file_id,
        changes=orchestrator.get_session_data(CHANGES_KEY) or {},
        formset=review_page.formset,
    )
    orchestrator.set_session_data(CHANGES_KEY, merged_changes)
    orchestrator.set_session_data(VALIDATION_SUMMARY_KEY, None)

    review_action = request.POST.get("review_action")
    next_page = current_page
    if review_action == "previous_page":
        next_page = max(current_page - 1, 1)
    elif review_action == "next_page":
        next_page = min(current_page + 1, review_page.total_pages)

    orchestrator.set_session_data(REVIEW_PAGE_KEY, next_page)
    view._review_page_number_override = next_page
    view._review_page = None


def ctx_confirm_step(request: HttpRequest, view:"BloomerpBulkUploadView", orchestrator: BaseStateOrchestrator):
    file_id = orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
    if not file_id:
        return {}

    validation_summary = view.service.build_validation_summary(
        file_id=file_id,
        changes=orchestrator.get_session_data(CHANGES_KEY) or {},
    )
    orchestrator.set_session_data(VALIDATION_SUMMARY_KEY, validation_summary.as_dict())
    changes = orchestrator.get_session_data(CHANGES_KEY) or {}

    return {
        "validation_summary": validation_summary,
        "changed_row_count": len(changes),
        "changed_cell_count": sum(len(row_changes) for row_changes in changes.values()),
        "selected_fields": orchestrator.get_session_data(SELECTED_FIELDS_KEY) or [],
        "wizard_submit_label": "Import objects",
    }


@router.register(
    path="bulk-upload",
    name="Bulk Upload {model}",
    url_name="bulk_upload",
    description="Bulk upload objects from {model}",
    route_type="model",
    exclude_models=[File],
)
class BloomerpBulkUploadView(PermissionRequiredMixin, WizardMixin, HtmxMixin, TemplateView):
    model = None
    module = None
    state_orchestrator_cls = BaseStateOrchestrator
    steps = [
        WizardStep(
            name="Upload file",
            description="Download a template or upload a completed spreadsheet to start a draft.",
            template_name="list_views/bulk_upload_wizard/upload_step.html",
            context_func=ctx_upload_step,
            process_func=pcs_upload_step,
        ),
        WizardStep(
            name="Review rows",
            description="Review the uploaded rows page by page and apply any corrections before import.",
            template_name="list_views/bulk_upload_wizard/review_step.html",
            context_func=ctx_review_step,
            process_func=pcs_review_step,
        ),
        WizardStep(
            name="Confirm import",
            description="Validate the full draft and confirm the import.",
            template_name="list_views/bulk_upload_wizard/confirm_step.html",
            context_func=ctx_confirm_step,
            process_func=None,
        ),
    ]

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        self.model_content_type = ContentType.objects.get_for_model(self.model)
        self.session_key = f"bulk_upload_wizard_{self.model._meta.label_lower}"
        self.success_message_key = f"{self.session_key}__success_message"
        self._keep_draft_file = False
        self.service = BulkCrudService(model=self.model, user=request.user)
        self._upload_form = None
        self._review_page = None
        self._review_page_number_override = None
        super().setup(request, *args, **kwargs)

    def has_permission(self):
        manager = UserPermissionManager(self.request.user)
        return manager.has_global_permission(
            self.model,
            create_permission_str(self.model, "bulk_add"),
        )

    def get_htmx_include_addendum(self) -> bool:
        htmx_target = getattr(self.request.htmx, "target", None)
        return htmx_target in {None, self.htmx_main_target}

    def clear_state(self):
        draft_file_id = None
        try:
            draft_file_id = self.orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
        except Exception:
            draft_file_id = None

        if draft_file_id and not self._keep_draft_file:
            self.service.delete_draft_file(draft_file_id)
        super().clear_state()

    def pop_success_message(self) -> str | None:
        message = self.request.session.pop(self.success_message_key, None)
        if message is not None:
            self.request.session.modified = True
        return message

    def set_success_message(self, message: str) -> None:
        self.request.session[self.success_message_key] = message
        self.request.session.modified = True

    def normalize_step_index(self, step: int) -> int:
        step = super().normalize_step_index(step)
        if step > 0 and not self.orchestrator.get_session_data(DRAFT_FILE_ID_KEY):
            return 0
        return step

    def get_review_page_number(self) -> int:
        if self._review_page_number_override is not None:
            try:
                return max(int(self._review_page_number_override), 1)
            except (TypeError, ValueError):
                pass

        page_value = (
            self.request.POST.get("review_page")
            or self.request.GET.get("review_page")
            or self.orchestrator.get_session_data(REVIEW_PAGE_KEY)
            or 1
        )
        try:
            return max(int(page_value), 1)
        except (TypeError, ValueError):
            return 1

    def get_review_page_size(self) -> int:
        page_size = self.orchestrator.get_session_data(PAGE_SIZE_KEY) or DEFAULT_REVIEW_PAGE_SIZE
        try:
            return max(int(page_size), 1)
        except (TypeError, ValueError):
            return DEFAULT_REVIEW_PAGE_SIZE

    def should_advance_after_process(self, step: int) -> bool:
        if step == 1 and self.request.POST.get("review_action") in {"previous_page", "next_page"}:
            return False
        return super().should_advance_after_process(step)

    def done(self):
        file_id = self.orchestrator.get_session_data(DRAFT_FILE_ID_KEY)
        if not file_id:
            return redirect(self.request.path)

        changes = self.orchestrator.get_session_data(CHANGES_KEY) or {}
        validation_summary = self.service.build_validation_summary(file_id=file_id, changes=changes)
        self.orchestrator.set_session_data(VALIDATION_SUMMARY_KEY, validation_summary.as_dict())

        if not validation_summary.is_valid:
            return WizardError(
                message="The draft still contains validation errors. Review the rows before importing.",
                title="Import blocked",
                step=2,
            )

        status, created_count = self.service.process_draft(file_id=file_id, changes=changes)
        self._keep_draft_file = status == "queued"
        if status == "queued":
            self.set_success_message(f"Bulk upload queued for {created_count} row(s).")
        else:
            self.set_success_message(f"Created {created_count} object(s) successfully.")

        if self.request.htmx:
            return HttpResponseClientRedirect(self.request.path)
        return redirect(self.request.path)

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["content_type_id"] = self.model_content_type.pk
        return context
