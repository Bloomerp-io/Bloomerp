"""Reusable preparation, action selection, and signing/delivery wizard steps."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_htmx.http import HttpResponseClientRefresh
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import get_signing_preparation
from bloomerp.document_signing.requests import (
    create_signature_request,
    signing_evidence,
)
from bloomerp.models.document_signing import SignaturePreparation, SignatureRequest
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.views.mixins.wizard_mixin import (
    BaseStateOrchestrator,
    WizardError,
    WizardMixin,
    WizardStep,
)


def preparation_context(
    request: HttpRequest, view: SigningWizardMixin, state: BaseStateOrchestrator
) -> dict[str, Any]:
    """Load the existing preparation component inside the wizard-owned form."""
    params = {"embedded": "1"}
    template_id = view.get_signing_template_id()
    if template_id:
        params["document_template_id"] = template_id
    if state.get_session_data("preparation_id"):
        params["preparation_id"] = state.get_session_data("preparation_id")
    url = reverse(
        "components_document_signing_prepare_sign",
        kwargs={"file_id": view.get_signing_file().pk},
    )
    return {"signing_component_url": f"{url}?{urlencode(params)}"}


def process_preparation(
    request: HttpRequest, view: SigningWizardMixin, state: BaseStateOrchestrator
) -> WizardError | None:
    """Accept only a saved, readable preparation for this PDF and its current revision."""
    try:
        preparation = get_signing_preparation(
            UserPolicyManager(request.user),
            str(view.get_signing_file().pk),
            request.POST.get("preparation_id", ""),
        )
        if preparation.revision != int(request.POST.get("preparation_revision", "0")):
            raise ValueError("Stale preparation")
        if (
            not preparation.fields.exists()
            or preparation.roles.filter(fields__isnull=True).exists()
        ):
            raise ValueError("Missing signer fields")
    except (APIException, Http404, DjangoValidationError, ValueError, TypeError):
        return WizardError(
            message=_("Give every signer at least one field before continuing."),
            step=view.get_signing_step_offset(),
        )
    if (
        state.get_session_data("preparation_id") != str(preparation.pk)
        or state.get_session_data("preparation_revision") != preparation.revision
    ):
        view.clear_signing_action()
    state.set_session_data("preparation_id", str(preparation.pk))
    state.set_session_data("preparation_revision", preparation.revision)
    return None


def action_context(
    request: HttpRequest, view: SigningWizardMixin, state: BaseStateOrchestrator
) -> dict[str, Any]:
    """Restore the action choice while retaining the saved preparation."""
    return {"selected_action": state.get_session_data("signing_action") or ""}


def process_action(
    request: HttpRequest, view: SigningWizardMixin, state: BaseStateOrchestrator
) -> WizardError | HttpResponse | None:
    """Choose delivery or signing, or immediately save a recipient-free prepared request."""
    action = request.POST.get("signing_action")
    if action not in {"send", "self", "complete"}:
        return WizardError(
            message=_("Choose how to complete this signing request."),
            step=view.get_signing_step_offset() + 1,
        )
    if action != state.get_session_data("signing_action"):
        view.clear_signing_action()
    state.set_session_data("signing_action", action)
    if not state.get_session_data("dispatch_id"):
        state.set_session_data("dispatch_id", str(uuid4()))
    if action == "complete":
        try:
            preparation = view.get_wizard_preparation()
            create_signature_request(
                UserPolicyManager(request.user),
                view.get_signing_file(),
                preparation,
                preparation.revision,
                UUID(state.get_session_data("dispatch_id")),
                {},
                None,
                "",
                None,
                signing_evidence(request.META),
                draft_only=True,
            )
        except (APIException, DjangoValidationError) as error:
            return WizardError(
                message=str(error), step=view.get_signing_step_offset() + 1
            )
        return view._handle_done(current_step=view.get_signing_step_offset() + 1)
    return None


def completion_context(
    request: HttpRequest, view: SigningWizardMixin, state: BaseStateOrchestrator
) -> dict[str, Any]:
    """Embed the existing final action or resume a recorded completion for page refresh."""
    file = view.get_signing_file()
    preparation = view.get_wizard_preparation()
    completed = view.get_finished_request()
    if completed:
        return {"completed_request": completed}
    action = state.get_session_data("signing_action")
    route = (
        "components_document_signing_send_signature_request"
        if action in {"send", "complete"}
        else "components_document_signing_start_self_signing"
    )
    params = {"preparation_id": str(preparation.pk)}
    if action in {"send", "complete"}:
        params["submission_id"] = state.get_session_data("dispatch_id")
    return {
        "signing_component_url": reverse(route, kwargs={"file_id": file.pk})
        + "?"
        + urlencode(params),
    }


class SigningWizardMixin(WizardMixin):
    """Compose three signing steps after an optional source-selection prefix."""

    def get_signing_step_offset(self) -> int:
        """Start standalone signing at preparation; source wizards override this offset."""
        return 0

    def get_signing_template_id(self) -> str | None:
        """Leave template selection open when the entry point starts from an existing file."""
        return None

    def get_signing_file(self) -> FileNode:
        """Resolve the authorized PDF supplied by the concrete wizard entry point."""
        raise NotImplementedError("Provide the wizard's signing PDF.")

    def clear_signing_action(self) -> None:
        """Invalidate the chosen action and dispatch identity when its preparation changes."""
        for key in ("signing_action", "dispatch_id", "completed_request_id"):
            self.orchestrator.set_session_data(key, None)

    def clear_signing_preparation(self) -> None:
        """Discard downstream wizard references when the original PDF changes."""
        self.clear_signing_action()
        for key in ("preparation_id", "preparation_revision"):
            self.orchestrator.set_session_data(key, None)

    def get_wizard_preparation(self) -> SignaturePreparation:
        """Recheck the current actor's access and the file/preparation binding."""
        return get_signing_preparation(
            UserPolicyManager(self.request.user),
            str(self.get_signing_file().pk),
            self.orchestrator.get_session_data("preparation_id") or "",
        )

    def normalize_step_index(self, step: int) -> int:
        """Prevent action selection or completion without an up-to-date saved preparation."""
        offset = self.get_signing_step_offset()
        step = min(max(step, 0), offset + 2)
        if step <= offset:
            return step
        try:
            preparation = self.get_wizard_preparation()
        except (APIException, Http404, DjangoValidationError, ValueError, TypeError):
            self.clear_signing_preparation()
            return offset
        if preparation.revision != self.orchestrator.get_session_data(
            "preparation_revision"
        ):
            self.clear_signing_action()
            return offset
        if step == offset + 2 and self.orchestrator.get_session_data(
            "signing_action"
        ) not in {"self", "send", "complete"}:
            return offset + 1
        return step

    def get_step(self, step: int) -> WizardStep | None:
        """Return reusable preparation, action-choice, and final-action definitions."""
        relative_step = step - self.get_signing_step_offset()
        if relative_step == 0:
            return WizardStep(
                name=_("Prepare document"),
                template_name="views/document_signing/wizard/prepare.html",
                context_func=preparation_context,
                process_func=process_preparation,
            )
        if relative_step == 1:
            return WizardStep(
                name=_("Choose signing action"),
                template_name="views/document_signing/wizard/action.html",
                context_func=action_context,
                process_func=process_action,
            )
        if relative_step == 2:
            return WizardStep(
                name={
                    "send": _("Send signature request"),
                    "self": _("Sign document"),
                    "complete": _("Complete without sending"),
                }.get(
                    self.orchestrator.get_session_data("signing_action"),
                    _("Sign document"),
                ),
                template_name="views/document_signing/wizard/complete.html",
                context_func=completion_context,
            )
        return None

    def get_finished_request(self) -> SignatureRequest | None:
        """Find an already created or self-signed result without repeating its operation."""
        state = self.orchestrator
        queryset = (
            UserPolicyManager(self.request.user)
            .get_accessible_queryset(SignatureRequest, "view")
            .filter(
                created_by=self.request.user,
                source_preparation_id=state.get_session_data("preparation_id"),
                source_preparation_revision=state.get_session_data(
                    "preparation_revision"
                ),
                original_file=self.get_signing_file(),
            )
        )
        if state.get_session_data("signing_action") in {"send", "complete"}:
            identity = uuid5(
                NAMESPACE_URL,
                f"bloomerp:dispatch:{self.request.user.pk}:{state.get_session_data('dispatch_id')}",
            )
            return queryset.filter(pk=identity).first()
        return queryset.filter(
            pk=state.get_session_data("completed_request_id"),
            recipients__user=self.request.user,
            recipients__status="signed",
        ).first()

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Validate a finished component operation before clearing state and reloading the page."""
        step = self.get_current_step_index()
        if (
            step == self.get_signing_step_offset() + 2
            and request.POST.get("_wizard_action") == "completed"
        ):
            try:
                identity = forms.UUIDField().clean(request.POST.get("request_id"))
            except DjangoValidationError:
                return HttpResponse(status=400)
            completed = (
                UserPolicyManager(request.user)
                .get_accessible_queryset(SignatureRequest, "view")
                .filter(
                    pk=identity,
                    created_by=request.user,
                    original_file=self.get_signing_file(),
                    source_preparation_id=self.orchestrator.get_session_data(
                        "preparation_id"
                    ),
                    source_preparation_revision=self.orchestrator.get_session_data(
                        "preparation_revision"
                    ),
                )
                .first()
            )
            if completed is None or (
                self.orchestrator.get_session_data("signing_action") == "self"
                and not completed.recipients.filter(
                    user=request.user, status="signed"
                ).exists()
            ):
                return HttpResponse(status=400)
            return self._handle_done(current_step=step)
        if step == self.get_signing_step_offset() + 2 and (
            self.get_finished_request() or request.POST.get("_wizard_action") != "back"
        ):
            return self.render_step(step)
        return super().post(request, *args, **kwargs)

    def done(self) -> HttpResponse:
        """Reload the current page after the shared wizard clears its completed state."""
        return HttpResponseClientRefresh()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Let final components own their forms while keeping shared wizard navigation."""
        context = super().get_context_data(**kwargs)
        final = context["step_index"] == self.get_signing_step_offset() + 2
        context["wizard_hide_submit"] = final
        context["wizard_step_owns_form"] = final
        context["wizard_complete"] = final and bool(context.get("completed_request"))
        return context
