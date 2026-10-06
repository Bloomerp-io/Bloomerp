"""Provider-aware reconfiguration of an existing agent using the create wizard."""

from typing import Any, ClassVar

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django_htmx.http import HttpResponseClientRefresh

from bloomerp.agents.providers import AI_PROVIDER_REGISTRY
from bloomerp.forms.agents.ai_agent import AIAgentDetailsForm
from bloomerp.models.agents import AIAgent
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.agents.create_ai_agent import CreateAIAgentView
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.wizard_mixin import WizardError


@router.register(
    path="reconfigure",
    route_type="detail",
    name="Reconfigure",
    url_name="reconfigure",
    models=AIAgent,
    description="Reconfigure an AI agent",
)
class ReconfigureAIAgentView(CreateAIAgentView, BaseBloomerpDetailView):
    """Reuse both creation steps while updating the same permission-checked agent."""

    is_detail_view = True
    required_fields: ClassVar[set[str]] = {"provider", "name", "model_identifier"}

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        """Isolate each agent's wizard state and preload its current provider."""
        self.session_key = f"ai_agent_reconfigure_{kwargs['pk']}"
        super().setup(request, *args, **kwargs)
        self.object = self.get_object()
        if not self.orchestrator.get_session_data("provider"):
            self.orchestrator.set_session_data("provider", self.object.provider)

    def get_object(self, queryset: QuerySet[AIAgent] | None = None) -> AIAgent:
        """Resolve the current record for detail framing and mutation checks."""
        return super().get_object(queryset=queryset)

    def allowed_fields(self) -> set[str] | None:
        """Resolve change grants against this particular agent rather than all rows."""
        if self.request.user.is_superuser:
            return None
        return set(
            UserPolicyManager(self.request.user)
            .get_accessible_fields_for_object(self.object, "change")
            .values_list("field", flat=True)
        )

    def has_permission(self) -> bool:
        """Require configuration change access on every request, including final POST."""
        manager = UserPolicyManager(self.request.user)
        allowed = self.allowed_fields()
        return manager.has_access_to_object(self.object, "change") and (
            allowed is None or self.required_fields.issubset(allowed)
        )

    def build_form(self, data: Any = None) -> AIAgentDetailsForm:
        """Populate the current settings and keep credential inputs unfilled."""
        provider = AI_PROVIDER_REGISTRY.get(
            self.orchestrator.get_session_data("provider") or ""
        )
        if provider is None:
            raise PermissionDenied("Select a provider first")
        return AIAgentDetailsForm(
            data=data,
            instance=self.object,
            provider=provider,
            allowed_fields=self.allowed_fields(),
            user=self.request.user,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Keep detail tabs visible and label the final action as saving changes."""
        context = super().get_context_data(**kwargs)
        if context["step_index"] == 1:
            context["wizard_submit_label"] = _("Save changes")
        return context

    def done(self) -> HttpResponse | WizardError:
        """Persist authorized changes atomically and reload the full page after success."""
        with transaction.atomic():
            self.object = AIAgent.objects.select_for_update().get(pk=self.object.pk)
            if not self.has_permission():
                raise PermissionDenied("Agent configuration access was revoked.")
            form = self.build_form(data=self.request.POST)
            self.details_form = form
            if not form.is_valid():
                return WizardError(message=_("Review the highlighted fields."), step=1)
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
                raise PermissionDenied(
                    "Agent fields are outside your change permissions."
                )
            candidate = form.save(commit=False)
            candidate.updated_by = self.request.user
            if not form.keep_credentials and not form.credentials:
                form.add_error(None, _("Enter credentials for the selected provider."))
                return WizardError(message=_("Review the agent details."), step=1)
            if form.credentials:
                candidate.set_credentials(form.credentials)
            manager = UserPolicyManager(self.request.user)
            if not manager.candidate_matches_row_policies(candidate, "change"):
                raise PermissionDenied("Agent changes are outside your permitted rows.")
            try:
                # Use a savepoint so a database error does not break the outer
                # transaction before the form is rendered again.
                with transaction.atomic():
                    candidate.save()
                    if allowed is not None:
                        row_fields = set(
                            manager.get_accessible_fields_for_object(
                                candidate, "change"
                            ).values_list("field", flat=True)
                        )
                        if not posted_roots.issubset(row_fields):
                            raise PermissionDenied(
                                "Agent fields are outside your permitted rows."
                            )
                    form.save_m2m()
            except (ValidationError, IntegrityError):
                form.add_error(
                    None,
                    _("The agent could not be saved. Check its name and settings."),
                )
                return WizardError(message=_("Review the agent details."), step=1)
        self.add_message(text=_("AI agent updated successfully."), type="success")
        if self.request.htmx:
            return HttpResponseClientRefresh()
        return redirect(self.request.path)
