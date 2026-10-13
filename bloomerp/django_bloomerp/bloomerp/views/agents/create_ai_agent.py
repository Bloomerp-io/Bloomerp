"""Two-step, permission-enforced AI agent creation with encrypted credentials."""

from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY
from bloomerp.forms.agents.ai_agent import AIAgentDetailsForm
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.agents import AIAgent
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_form_mixin import LayoutFormMixin
from bloomerp.views.mixins.wizard_mixin import (
    BaseStateOrchestrator,
    WizardError,
    WizardMixin,
    WizardStep,
)


class AIAgentDetailsLayout(LayoutFormMixin):
    """Render dynamic provider controls through the shared form layout widgets."""

    ts_item_component = "detail-view-value"

    def __init__(self, form: AIAgentDetailsForm) -> None:
        """Retain the current bound form, including validation errors and field grants."""
        self.form = form

    def get_form(self, form_class: Any = None) -> AIAgentDetailsForm:
        """Supply the existing wizard form rather than constructing a second form."""
        return self.form

    def resolve_form_label(self, item: LayoutItem) -> str:
        """Resolve translated labels before serializing the shared layout metadata."""
        return str(self.form[str(item.id)].label)

    def get_layout(self) -> FieldLayout:
        """Group settings with paired access controls in a three-column tools section."""
        sections = [
            (
                _("Agent details"),
                [
                    "name",
                    "model_identifier",
                    "base_url",
                    "enabled",
                    "default_instructions",
                ],
            ),
            (
                _("Tools"),
                [
                    "internal_tool_mode",
                    "internal_tools",
                    "internal_resource_mode",
                    "internal_resources",
                    "mcp_integrations",
                ],
            ),
            (
                _("Provider credentials"),
                list(self.form.schema_fields["credentials_encrypted"].values()),
            ),
            (
                _("Run limits"),
                [
                    "request_timeout_seconds",
                    "max_tokens",
                    "max_tool_calls",
                    "max_duration_seconds",
                ],
            ),
            (
                _("Provider parameters"),
                list(self.form.schema_fields["parameters"].values()),
            ),
        ]
        field_spans = {
            "default_instructions": 2,
            "parameter__stop_sequences": 2,
            "internal_tool_mode": 1,
            "internal_tools": 2,
            "internal_resource_mode": 1,
            "internal_resources": 2,
            "mcp_integrations": 3,
        }
        return FieldLayout(
            rows=[
                LayoutRow(
                    columns=3 if "mcp_integrations" in names else 2,
                    title=str(title),
                    items=[
                        LayoutItem(
                            id=name,
                            colspan=field_spans.get(name, 1),
                        )
                        for name in names
                        if name in self.form.fields
                    ],
                )
                for title, names in sections
                if any(name in self.form.fields for name in names)
            ]
        )


def provider_context(
    request: HttpRequest, view: CreateAIAgentView, orchestrator: BaseStateOrchestrator
) -> dict[str, Any]:
    """Render registered providers using only safe names and stable identifiers."""
    return {
        "providers": AI_PROVIDER_REGISTRY.values(),
        "selected_provider": orchestrator.get_session_data("provider") or "",
    }


def process_provider(
    request: HttpRequest, view: CreateAIAgentView, orchestrator: BaseStateOrchestrator
) -> WizardError | None:
    """Persist only the selected provider identifier as the prerequisite for step two."""
    provider = AI_PROVIDER_REGISTRY.get(request.POST.get("provider", ""))
    if provider is None:
        return WizardError(message=_("Select an AI provider to continue."), step=0)
    orchestrator.set_session_data("provider", provider.id)
    return None


def details_context(
    request: HttpRequest, view: CreateAIAgentView, orchestrator: BaseStateOrchestrator
) -> dict[str, Any]:
    """Render structured model inputs, retaining errors without retaining credentials in sessions."""
    form = view.details_form or view.build_form()
    return {
        "form": form,
        "provider_label": form.provider.name,
        "model_fields": [
            form[name] for name in form.Meta.fields if name in form.fields
        ],
        "credential_fields": form.group_fields("credentials_encrypted"),
        "parameter_fields": form.group_fields("parameters"),
        "details_layout": AIAgentDetailsLayout(form).get_transformed_layout(),
    }


def process_details(
    request: HttpRequest, view: CreateAIAgentView, orchestrator: BaseStateOrchestrator
) -> WizardError | None:
    """Validate final-step inputs in the request without copying secrets into wizard state."""
    view.details_form = view.build_form(data=request.POST)
    if not view.details_form.is_valid():
        return WizardError(message=_("Review the highlighted fields."), step=1)
    return None


@router.register(
    path="create",
    route_type="model",
    name="Create {model}",
    url_name="add",
    models=AIAgent,
    override=True,
    description="Create an AI agent",
)
class CreateAIAgentView(WizardMixin, BaseBloomerpView, TemplateView):
    """Replace the generated create route with exactly two provider-aware steps."""

    model = AIAgent
    template_name = "views/base_wizard.html"
    session_key = "ai_agent_create_wizard"
    details_form: AIAgentDetailsForm | None = None
    required_fields: ClassVar[set[str]] = {
        "provider",
        "name",
        "model_identifier",
        "credentials_encrypted",
    }

    def allowed_fields(self) -> set[str] | None:
        """Resolve writable model fields through the existing policy manager."""
        if self.request.user.is_superuser:
            return None
        return set(
            UserPolicyManager(self.request.user)
            .get_accessible_fields(AIAgent, "add")
            .values_list("field", flat=True)
        )

    def has_permission(self) -> bool:
        """Require model creation and the essential field grants on every request."""
        manager = UserPolicyManager(self.request.user)
        allowed = self.allowed_fields()
        return manager.has_global_permission(AIAgent, "add") and (
            allowed is None or self.required_fields.issubset(allowed)
        )

    def normalize_step_index(self, step: int) -> int:
        """Prevent direct navigation past provider selection or beyond the two-step flow."""
        if (
            AI_PROVIDER_REGISTRY.get(
                self.orchestrator.get_session_data("provider") or ""
            )
            is None
        ):
            return 0
        return min(max(step, 0), 1)

    def build_form(self, data: Any = None) -> AIAgentDetailsForm:
        """Build the second step using the server-selected provider and current field grants."""
        provider = AI_PROVIDER_REGISTRY.get(
            self.orchestrator.get_session_data("provider") or ""
        )
        if provider is None:
            raise PermissionDenied("Select a provider first")
        return AIAgentDetailsForm(
            data=data,
            provider=provider,
            allowed_fields=self.allowed_fields(),
            user=self.request.user,
        )

    def get_step(self, step: int) -> WizardStep | None:
        """Declare provider selection and configuration as the only wizard steps."""
        if step == 0:
            return WizardStep(
                name=_("Select provider"),
                template_name="views/agents/create_ai_agent/select_provider.html",
                description=_("Choose the provider for this AI agent."),
                context_func=provider_context,
                process_func=process_provider,
            )
        if step == 1:
            return WizardStep(
                name=_("Configure agent"),
                template_name="views/agents/create_ai_agent/configure_agent.html",
                description=_("Enter agent settings and provider credentials."),
                context_func=details_context,
                process_func=process_details,
            )
        return None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Label the final action as model creation rather than another wizard step."""
        context = super().get_context_data(**kwargs)
        if context["step_index"] == 1:
            context["wizard_submit_label"] = _("Create AI agent")
        return context

    def done(self) -> HttpResponse | WizardError:
        """Encrypt credentials and authorize the complete candidate before atomically saving."""
        form = self.details_form
        if form is None or not form.is_valid():
            return WizardError(message=_("Complete the agent details first."), step=1)
        allowed = self.allowed_fields()
        posted_roots = (
            {
                root
                for name, root in form.field_roots.items()
                if name in self.request.POST
            }
            | self.required_fields
            | (
                {
                    "internal_tool_mode",
                    "internal_tools",
                    "internal_resource_mode",
                    "internal_resources",
                    "mcp_integrations",
                }
                & form.fields.keys()
            )
        )
        if allowed is not None and not posted_roots.issubset(allowed):
            raise PermissionDenied("Model fields are outside your creation permissions")
        candidate = form.save(commit=False)
        candidate.created_by = self.request.user
        candidate.updated_by = self.request.user
        candidate.set_credentials(form.credentials)
        if not UserPolicyManager(self.request.user).candidate_matches_row_policies(
            candidate, "add"
        ):
            raise PermissionDenied("Model creation is outside your permitted rows")
        try:
            with transaction.atomic():
                candidate.save()
                if allowed is not None:
                    row_fields = set(
                        UserPolicyManager(self.request.user)
                        .get_accessible_fields_for_object(candidate, "add")
                        .values_list("field", flat=True)
                    )
                    if not posted_roots.issubset(row_fields):
                        raise PermissionDenied(
                            "Model fields are outside your permitted rows"
                        )
                form.save_m2m()
        except (ValidationError, IntegrityError):
            form.add_error(
                None, _("The agent could not be saved. Check its name and settings.")
            )
            return WizardError(message=_("Review the agent details."), step=1)
        self.add_message(text=_("AI agent created successfully."), type="success")
        return redirect(candidate.get_absolute_url())
