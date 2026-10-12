"""Staff-accessible provider selection and typed IM connection configuration."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.views.generic import TemplateView

from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.forms.communication.im_connection import IMConnectionForm
from bloomerp.models.communication.instant_messaging import (
    IMAuthorization,
    IMConnection,
)
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.wizard_mixin import (
    BaseStateOrchestrator,
    WizardError,
    WizardMixin,
    WizardStep,
)


def provider_context(
    request: HttpRequest,
    view: CreateIMConnectionView,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Offer every registered external provider, keeping internal messaging implicit."""
    return {
        "providers": [
            provider
            for provider in IM_PROVIDER_REGISTRY.values()
            if not provider.internal
        ],
        "selected_provider": orchestrator.get_session_data("provider") or "",
    }


def process_provider(
    request: HttpRequest,
    view: CreateIMConnectionView,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Persist only a validated external-provider key as the wizard prerequisite."""
    provider = IM_PROVIDER_REGISTRY.get(request.POST.get("provider", ""))
    if provider is None or provider.internal:
        return WizardError(message="Select an external messaging provider.", step=0)
    orchestrator.set_session_data("provider", provider.key)
    return None


def configuration_context(
    request: HttpRequest,
    view: CreateIMConnectionView,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Keep submitted validation errors local to this request, including secret fields."""
    form = view.configuration_form or view.build_form()
    return {"form": form, "provider_label": form.provider.display_name}


def process_configuration(
    request: HttpRequest,
    view: CreateIMConnectionView,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Validate configuration without copying credentials into wizard state."""
    view.configuration_form = view.build_form(data=request.POST)
    if not view.configuration_form.is_valid():
        return WizardError(message="Review the highlighted fields.", step=1)
    return None


@router.register(
    path="create",
    route_type="model",
    name="Create {model}",
    url_name="add",
    models=IMConnection,
    override=True,
    description="Create an instant messaging connection",
)
class CreateIMConnectionView(WizardMixin, BaseBloomerpView, TemplateView):
    """Override generated creation with a two-step wizard available to active staff."""

    model = IMConnection
    template_name = "views/base_wizard.html"
    session_key = "im_connection_create_wizard"
    configuration_form: IMConnectionForm | None = None

    def has_permission(self) -> bool:
        """Grant this setup workflow to every active staff user without broad model grants."""
        user = self.request.user
        return user.is_authenticated and user.is_active and user.is_staff

    def normalize_step_index(self, step: int) -> int:
        """Prevent direct configuration or completion before selecting an external provider."""
        provider = IM_PROVIDER_REGISTRY.get(
            self.orchestrator.get_session_data("provider") or ""
        )
        return min(max(step, 0), 1) if provider and not provider.internal else 0

    def build_form(self, data: Any = None) -> IMConnectionForm:
        """Resolve the provider from server-side wizard state rather than posted overrides."""
        provider = IM_PROVIDER_REGISTRY.get(
            self.orchestrator.get_session_data("provider") or ""
        )
        if provider is None or provider.internal:
            raise PermissionDenied("Select an external provider first.")
        return IMConnectionForm(data=data, provider=provider)

    def get_step(self, step: int) -> WizardStep | None:
        """Declare provider choice followed by provider-defined configuration."""
        if step == 0:
            return WizardStep(
                name="Select provider",
                template_name="views/communication/create_im_connection/provider.html",
                context_func=provider_context,
                process_func=process_provider,
            )
        if step == 1:
            return WizardStep(
                name="Configure connection",
                template_name="views/communication/create_im_connection/configuration.html",
                context_func=configuration_context,
                process_func=process_configuration,
            )
        return None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Give the final wizard action an explicit creation label."""
        context = super().get_context_data(**kwargs)
        if context["step_index"] == 1:
            context["wizard_submit_label"] = "Create connection"
        return context

    def done(self) -> HttpResponse | WizardError:
        """Atomically persist a draft connection with encrypted authorization credentials."""
        form = self.configuration_form
        if form is None or not form.is_valid() or form.configuration is None:
            return WizardError(message="Complete the connection configuration.", step=1)
        settings, credentials = form.split_configuration()
        try:
            with transaction.atomic():
                connection = IMConnection.objects.create(
                    name=form.configuration.name,
                    provider=form.provider.key,
                    external_account_id=form.configuration.external_account_id(),
                    settings=settings,
                    status="draft",
                    created_by=self.request.user,
                    updated_by=self.request.user,
                )
                if credentials:
                    authorization = IMAuthorization(
                        connection=connection, kind="shared"
                    )
                    authorization.set_credentials(credentials)
                    authorization.save()
        except ValidationError:
            form.add_error(
                None, "The connection could not be saved. Check its settings."
            )
            return WizardError(message="Review the connection configuration.", step=1)
        self.template_name = "views/communication/create_im_connection/success.html"
        return self.render_to_response(
            self.get_context_data(connection_name=connection.name)
        )
