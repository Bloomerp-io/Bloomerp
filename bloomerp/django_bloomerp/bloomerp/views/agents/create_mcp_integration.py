"""Two-step MCP integration creation with shared outbound authentication."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.forms.agents.mcp_integration import MCPIntegrationForm
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.agents import MCPConnection, MCPIntegration
from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.compilers.python_permission_compiler import (
    PythonPermissionCompiler,
)
from bloomerp.permissions.definition import PermissionMatch
from bloomerp.permissions.manager import PolicyManager, UserPolicyManager
from bloomerp.router import router
from bloomerp.services.mcp.oauth import (
    MCPAuthenticationError,
    begin_authorization,
    client_metadata,
    exchange_code,
    seal,
    unseal,
    verify_api_key,
)
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_form_mixin import LayoutFormMixin
from bloomerp.views.mixins.wizard_mixin import WizardMixin, WizardStep


class MCPIntegrationLayout(LayoutFormMixin):
    """Render integration and authentication controls with the standard Bloomerp layout."""

    ts_item_component = "detail-view-value"

    def __init__(self, form: MCPIntegrationForm) -> None:
        """Retain bound fields and validation errors for the shared layout renderer."""
        self.form = form

    def get_form(self, form_class: Any = None) -> MCPIntegrationForm:
        """Return the current wizard form rather than constructing a new one."""
        return self.form

    def resolve_form_label(self, item: LayoutItem) -> str:
        """Resolve translated field labels into serializable layout metadata."""
        return str(self.form[str(item.id)].label)

    def get_layout(self) -> FieldLayout:
        """Group the server configuration and secret inputs into two-column sections."""
        return FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title=str(title),
                    items=[
                        LayoutItem(id=name, colspan=1)
                        for name in names
                        if name in self.form.fields
                    ],
                )
                for title, names in (
                    (
                        _("Server configuration"),
                        [
                            "name",
                            "enabled",
                            "endpoint_url",
                            "connection_mode",
                            "authentication_type",
                        ],
                    ),
                    (
                        _("Authentication configuration"),
                        [
                            "oauth_client_id",
                            "oauth_scopes",
                            "api_key",
                            "oauth_client_secret",
                        ],
                    ),
                )
            ]
        )


@router.register(
    path="create",
    route_type="model",
    name="Create {model}",
    url_name="add",
    models=MCPIntegration,
    override=True,
    description="Create an MCP integration",
)
class CreateMCPIntegrationView(WizardMixin, BaseBloomerpView, TemplateView):
    """Authenticate shared credentials, then review editable details before saving."""

    model = MCPIntegration
    session_key = "mcp_integration_create_wizard"
    template_name = "views/base_wizard.html"
    details_form: MCPIntegrationForm | None = None
    required_fields: ClassVar[set[str]] = {
        "name",
        "endpoint_url",
        "connection_mode",
        "authentication_type",
    }
    authentication_fields: ClassVar[tuple[str, ...]] = (
        "endpoint_url",
        "connection_mode",
        "authentication_type",
        "oauth_client_id",
        "oauth_scopes",
    )

    def allowed_fields(self) -> set[str] | None:
        """Resolve ordinary integration create grants through Bloomerp policies."""
        if self.request.user.is_superuser:
            return None
        return set(
            UserPolicyManager(self.request.user)
            .get_accessible_fields(MCPIntegration, "add")
            .values_list("field", flat=True)
        )

    def has_permission(self) -> bool:
        """Enforce create and essential field access on every step and callback."""
        allowed = self.allowed_fields()
        return UserPolicyManager(self.request.user).has_global_permission(
            MCPIntegration, "add"
        ) and (allowed is None or self.required_fields.issubset(allowed))

    def state_owned(self) -> bool:
        """Bind all wizard data to the current signed-in account."""
        return self.orchestrator.get_session_data("owner_id") == str(
            self.request.user.pk
        )

    def normalize_step_index(self, step: int) -> int:
        """Prevent direct access to review before valid settings and authentication."""
        if not self.state_owned() or not self.orchestrator.get_session_data(
            "configuration"
        ):
            return 0
        return (
            1 if step > 0 and self.orchestrator.get_session_data("review_ready") else 0
        )

    def get_step(self, step: int) -> WizardStep | None:
        """Declare configuration/authentication and final review as exactly two steps."""
        if step in (0, 1):
            return WizardStep(
                name=_("Configure server") if step == 0 else _("Review integration"),
                description=_(
                    "Shared accounts authenticate before review. Personal accounts are linked by each user later."
                )
                if step == 0
                else _(
                    "Edit details and save. Changing authentication settings requires reconnecting."
                ),
                template_name="views/agents/create_mcp_integration/details.html",
            )
        return None

    def callback_url(self) -> str:
        """Build the registered OAuth callback using the validated request host."""
        return self.request.build_absolute_uri(
            reverse("mcp_integrations_oauth_callback")
        )

    def build_form(self, data: Any = None) -> MCPIntegrationForm:
        """Keep secret inputs blank while restoring validated non-secret configuration."""
        configuration = (
            self.orchestrator.get_session_data("configuration")
            if self.state_owned()
            else {}
        )
        return MCPIntegrationForm(
            data=data,
            initial=configuration or {},
            allowed_fields=self.allowed_fields(),
            review=self.get_current_step_index() == 1,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Supply the shared form layout and only safe authentication review summaries."""
        context = super().get_context_data(**kwargs)
        form = self.details_form or self.build_form()
        context.update(
            form=form,
            details_layout=MCPIntegrationLayout(form).get_transformed_layout(),
            callback_url=self.callback_url(),
        )
        context["wizard_submit_label"] = (
            _("Save integration") if context["step_index"] == 1 else _("Next")
        )
        context["authentication_summary"] = (
            self.orchestrator.get_session_data("authentication_summary")
            if self.state_owned()
            else ""
        )
        return context

    def invalidate_authentication(self) -> None:
        """Discard credentials and outstanding authorization after any security-sensitive edit."""
        for key in (
            "connection",
            "pending_oauth",
            "client_secret",
            "authentication_summary",
            "review_ready",
        ):
            self.orchestrator.set_session_data(key, None)

    def fail(self, message: str, step: int = 0) -> HttpResponse:
        """Render a safe failure state without claiming authentication succeeded."""
        from bloomerp.views.mixins.wizard_mixin import WizardError

        self.set_wizard_error(
            WizardError(message=message, step=step), fallback_step=step
        )
        return self.render_step(step)

    def authorize_candidate(
        self, candidate: MCPIntegration, configuration: dict[str, Any]
    ) -> None:
        """Check row and field create permissions before outbound requests and final save."""
        candidate.created_by = self.request.user
        candidate.updated_by = self.request.user
        manager = UserPolicyManager(self.request.user)
        allowed = self.allowed_fields()
        posted_fields = set(self.request.POST) & set(MCPIntegrationForm.Meta.fields)
        if allowed is not None and not posted_fields.issubset(allowed):
            raise PermissionDenied(
                "Integration fields are outside your creation permissions."
            )
        if allowed is not None and not set(configuration).issubset(allowed):
            raise PermissionDenied(
                "Integration fields are outside your creation permissions."
            )
        if not manager.candidate_matches_row_policies(candidate, "add"):
            raise PermissionDenied(
                "Integration creation is outside your permitted rows."
            )
        if allowed is not None:
            row_fields = self.candidate_fields(candidate, manager)
            if not set(configuration).issubset(row_fields):
                raise PermissionDenied(
                    "Integration fields are outside your permitted rows."
                )

    def candidate_fields(
        self, candidate: MCPIntegration, manager: UserPolicyManager
    ) -> set[str]:
        """Resolve row-sensitive field grants with the existing compiler before persistence."""
        rules = manager.get_access_rules(MCPIntegration, "add")
        requested = PolicyManager._qualify_permission_codenames(MCPIntegration, "add")
        fields = BasePermissionCompiler.get_application_fields(rules, MCPIntegration)
        allowed: set[str] = set()
        for rule in rules:
            if (
                not PythonPermissionCompiler(
                    [rule], user=self.request.user, model=MCPIntegration
                )
                .compile(requested)
                .matches(candidate)
            ):
                continue
            for key, permissions in rule.field_permissions.items():
                if not BasePermissionCompiler.matches_requested_permissions(
                    permissions, requested, PermissionMatch.ANY
                ):
                    continue
                if key == "__all__":
                    allowed.update(field.field for field in fields.values())
                elif key in fields:
                    allowed.add(fields[key].field)
        return allowed

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Process settings, authenticate shared accounts and save only on final review."""
        step = self.get_current_step_index()
        if request.POST.get("_wizard_action") == "back":
            self.clear_wizard_error()
            return self.render_step(0)
        form = self.build_form(data=request.POST)
        self.details_form = form
        if not form.is_valid():
            # Invalid endpoint/auth edits must also make old credentials unusable.
            old = self.orchestrator.get_session_data("configuration") or {}
            if any(
                str(request.POST.get(field, "")) != str(old.get(field, ""))
                for field in self.authentication_fields
            ):
                self.invalidate_authentication()
                step = 0
            return self.fail(str(_("Review the highlighted fields.")), step)
        configuration = form.configuration()
        candidate = form.save(commit=False)
        self.authorize_candidate(candidate, configuration)
        old = self.orchestrator.get_session_data("configuration") or {}
        changed = not self.state_owned() or any(
            old.get(field, "") != configuration.get(field, "")
            for field in self.authentication_fields
        )
        entered_secret = form.cleaned_data.get("oauth_client_secret", "")
        entered_key = form.cleaned_data.get("api_key", "")
        if changed or entered_secret or entered_key:
            self.invalidate_authentication()
        self.orchestrator.set_session_data("owner_id", str(request.user.pk))
        self.orchestrator.set_session_data("configuration", configuration)
        shared = candidate.connection_mode == "shared"
        authentication = candidate.authentication_type
        if not shared or authentication == "none":
            self.invalidate_authentication()
            summary = (
                _("Each user links their own account later.")
                if not shared and authentication != "none"
                else _("This server requires no account credentials.")
            )
            self.orchestrator.set_session_data("authentication_summary", str(summary))
            self.orchestrator.set_session_data("review_ready", True)
        elif not self.orchestrator.get_session_data("review_ready"):
            try:
                if authentication == "api_key":
                    if not entered_key:
                        form.add_error(
                            "api_key", _("Enter the shared API key to continue.")
                        )
                        return self.fail(
                            str(
                                _(
                                    "Reconnect after changing the authentication settings."
                                )
                            )
                        )
                    status = verify_api_key(candidate.endpoint_url, entered_key)
                    connection = MCPConnection(integration=candidate, status=status)
                    connection.set_credentials({"api_key": entered_key})
                    self.orchestrator.set_session_data(
                        "connection",
                        {
                            "credentials_encrypted": connection.credentials_encrypted,
                            "status": status,
                            "verified_at": time.time(),
                        },
                    )
                    self.orchestrator.set_session_data("review_ready", True)
                    summary = (
                        _("Shared API key accepted by the server.")
                        if status == "ready"
                        else _(
                            "API key supplied. This server does not support an authentication probe; access remains unverified."
                        )
                    )
                    self.orchestrator.set_session_data(
                        "authentication_summary", str(summary)
                    )
                else:
                    location, pending = begin_authorization(
                        candidate.endpoint_url,
                        self.callback_url(),
                        request.build_absolute_uri(
                            reverse("mcp_integrations_oauth_client_metadata")
                        ),
                        client_id=candidate.oauth_client_id,
                        client_secret=entered_secret,
                        scopes=candidate.oauth_scopes,
                        owner_id=str(request.user.pk),
                    )
                    self.orchestrator.set_session_data("pending_oauth", seal(pending))
                    self.set_current_step_index(0)
                    return (
                        HttpResponseClientRedirect(location)
                        if request.htmx
                        else redirect(location)
                    )
            except (MCPAuthenticationError, ValidationError) as error:
                self.invalidate_authentication()
                return self.fail(
                    str(error)
                    if isinstance(error, MCPAuthenticationError)
                    else str(_("Invalid authentication values. Reconnect to continue."))
                )
        self.clear_wizard_error()
        if step == 1 and not changed and not entered_secret and not entered_key:
            return self.save_integration(candidate, configuration)
        return self.render_step(1)

    def save_integration(
        self, candidate: MCPIntegration, configuration: dict[str, Any]
    ) -> HttpResponse:
        """Atomically save the permitted integration and its optional encrypted shared account."""
        self.authorize_candidate(candidate, configuration)
        stored = self.orchestrator.get_session_data("connection")
        if (
            candidate.connection_mode == "shared"
            and candidate.authentication_type != "none"
            and not stored
        ):
            return self.fail(str(_("Authenticate the shared account before saving.")))
        if stored and stored.get("expires_at") and stored["expires_at"] <= time.time():
            self.invalidate_authentication()
            return self.fail(str(_("Authorization expired. Reconnect before saving.")))
        candidate.created_by = self.request.user
        candidate.updated_by = self.request.user
        try:
            with transaction.atomic():
                candidate.save()
                if stored:
                    connection = MCPConnection(
                        integration=candidate,
                        credentials_encrypted=stored["credentials_encrypted"],
                        status=stored["status"],
                        created_by=self.request.user,
                        updated_by=self.request.user,
                        last_checked_at=datetime.fromtimestamp(
                            stored["verified_at"], tz=UTC
                        ),
                    )
                    if stored.get("expires_at"):
                        connection.expires_at = datetime.fromtimestamp(
                            stored["expires_at"], tz=UTC
                        )
                    connection.save()
        except (ValidationError, IntegrityError, ValueError, OverflowError):
            return self.fail(
                str(_("The integration could not be saved. Review its settings.")), 1
            )
        self.clear_state()
        self.add_message(
            text=_("MCP integration created successfully."), type="success"
        )
        location = candidate.get_absolute_url()
        return (
            HttpResponseClientRedirect(location)
            if self.request.htmx
            else redirect(location)
        )


@router.register(
    path="create/oauth/callback",
    route_type="model",
    name="MCP OAuth callback",
    url_name="oauth_callback",
    models=MCPIntegration,
)
class MCPIntegrationOAuthCallbackView(CreateMCPIntegrationView):
    """Return shared OAuth authorization to review without creating model records."""

    http_method_names: ClassVar[list[str]] = ["get", "head", "options"]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Validate callback ownership/state/issuer, consume it once and encrypt issued tokens."""
        response = redirect(reverse("mcp_integrations_add"))
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        try:
            value = self.orchestrator.get_session_data("pending_oauth")
            if not self.state_owned() or not value:
                raise MCPAuthenticationError(
                    "No pending authorization for this account. Reconnect to continue."
                )
            pending = unseal(value)
            if pending["owner_id"] != str(
                request.user.pk
            ) or not secrets.compare_digest(
                pending["state"], request.GET.get("state", "")
            ):
                raise MCPAuthenticationError(
                    "The authorization state does not match. Reconnect to continue."
                )
            if time.time() - pending["started_at"] > 900:
                raise MCPAuthenticationError(
                    "Authorization expired. Reconnect to continue."
                )
            # Consume before exchanging tokens, including cancelled/failed authorization.
            self.orchestrator.set_session_data("pending_oauth", None)
            replay_key = "mcp_oauth_consumed:" + pending["state"]
            if not cache.add(replay_key, True, timeout=900):
                raise MCPAuthenticationError(
                    "This authorization callback has already been used."
                )
            issuer = request.GET.get("iss")
            if (issuer and issuer != pending["issuer"]) or (
                pending["require_issuer"] and not issuer
            ):
                raise MCPAuthenticationError(
                    "The authorization response issuer does not match."
                )
            if request.GET.get("error"):
                raise MCPAuthenticationError(
                    "Authorization was cancelled or denied. Reconnect to continue."
                )
            configuration = self.orchestrator.get_session_data("configuration") or {}
            if (
                configuration.get("endpoint_url") != pending["resource"]
                or configuration.get("connection_mode") != "shared"
                or configuration.get("authentication_type") != "oauth"
            ):
                raise MCPAuthenticationError(
                    "Server configuration changed. Reconnect to continue."
                )
            candidate = MCPIntegration(**configuration)
            self.authorize_candidate(candidate, configuration)
            code = request.GET.get("code", "")
            if not code:
                raise MCPAuthenticationError(
                    "The authorization server did not return a code. Reconnect to continue."
                )
            tokens = exchange_code(pending, code)
            connection = MCPConnection(integration=candidate, status="ready")
            connection.set_credentials(tokens["credentials"])
            self.orchestrator.set_session_data(
                "connection",
                {
                    "credentials_encrypted": connection.credentials_encrypted,
                    "status": "ready",
                    "verified_at": time.time(),
                    "expires_at": tokens["expires_at"],
                },
            )
            self.orchestrator.set_session_data("review_ready", True)
            self.orchestrator.set_session_data(
                "authentication_summary", str(_("Shared OAuth account authorized."))
            )
            self.clear_wizard_error()
            self.set_current_step_index(1)
        except (
            MCPAuthenticationError,
            ValidationError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            from bloomerp.views.mixins.wizard_mixin import WizardError

            self.invalidate_authentication()
            self.set_current_step_index(0)
            self.set_wizard_error(
                WizardError(
                    message=str(error)
                    if isinstance(error, MCPAuthenticationError)
                    else str(_("Authorization failed. Reconnect to continue.")),
                    step=0,
                ),
                fallback_step=0,
            )
        return response


@router.register(
    path="oauth/client-metadata.json",
    route_type="model",
    name="MCP OAuth client metadata",
    url_name="oauth_client_metadata",
    models=MCPIntegration,
)
class MCPIntegrationOAuthClientMetadataView(View):
    """Publish only public PKCE client metadata for compatible authorization servers."""

    http_method_names: ClassVar[list[str]] = ["get", "head", "options"]
    model = MCPIntegration
    module = None

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """Return the exact public client identifier and its registered callback."""
        metadata_url = request.build_absolute_uri(
            reverse("mcp_integrations_oauth_client_metadata")
        )
        callback_url = request.build_absolute_uri(
            reverse("mcp_integrations_oauth_callback")
        )
        return JsonResponse(client_metadata(metadata_url, callback_url))
