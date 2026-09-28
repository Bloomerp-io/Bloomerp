from __future__ import annotations

from django import forms
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.communication.emails.actions import get_mailboxes_for_account
from bloomerp.communication.utils.crypto import encrypt_email_secret
from bloomerp.communication.emails.email_providers import EmailProviderDefinition
from bloomerp.communication.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.models.communication import EmailAccount
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.wizard_mixin import BaseStateOrchestrator, WizardError, WizardMixin, WizardStep


CREATE_EMAIL_ACCOUNT_SESSION_KEY = "email_account_create_wizard"
PROVIDER_SESSION_KEY = "provider"
SETTINGS_SESSION_KEY = "settings"


class EmailAccountSettingsForm(forms.ModelForm):
    class Meta:
        model = EmailAccount
        fields = [
            "name",
            "email_address",
            "username",
            "password",
            "imap_host",
            "imap_port",
            "imap_security",
            "smtp_host",
            "smtp_port",
            "smtp_security",
            "save_sent_emails",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
            "oauth_scopes",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=False),
            "oauth_client_secret": forms.PasswordInput(render_value=False),
            "oauth_scopes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, provider: EmailProviderDefinition | str, **kwargs):
        super().__init__(*args, **kwargs)
        self.provider = (
            provider
            if isinstance(provider, EmailProviderDefinition)
            else EMAIL_PROVIDER_REGISTRY.get(provider)
        )
        if self.provider is not None:
            self.instance.provider = self.provider.key
        self._apply_field_styles()
        self._apply_provider_fields()

    def _apply_field_styles(self) -> None:
        """Style account inputs and the optional Sent-copy checkbox for setup."""
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input w-full")

        self.fields["save_sent_emails"].widget.attrs["class"] = "checkbox checkbox-primary"

        self.fields["name"].required = False
        self.fields["name"].widget.attrs.setdefault("placeholder", _("Accounting inbox"))
        self.fields["email_address"].widget.attrs.setdefault("placeholder", _("name@example.com"))
        self.fields["username"].required = False
        self.fields["username"].widget.attrs.setdefault("placeholder", _("Defaults to email address"))

    def _apply_provider_fields(self) -> None:
        if self.provider is None:
            self.fields.clear()
            return

        allowed_fields = self.provider.fields
        required_fields = set(self.provider.required_fields)
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True

        for field_name in list(self.fields):
            if field_name not in allowed_fields:
                self.fields.pop(field_name)

    def clean(self):
        cleaned_data = super().clean()
        email_address = cleaned_data.get("email_address")
        if email_address and not cleaned_data.get("username") and "username" in self.fields:
            cleaned_data["username"] = email_address
        return cleaned_data


def get_provider_context(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    selected_provider = orchestrator.get_session_data(PROVIDER_SESSION_KEY) or ""
    return {
        "selected_provider": selected_provider,
        "providers": [
            {
                "key": provider.key,
                "name": provider.name,
                "description": provider.description,
                "icon": provider.icon,
                "selected": selected_provider == provider.key,
            }
            for provider in EMAIL_PROVIDER_REGISTRY.values()
        ],
    }


def process_provider(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    provider = EMAIL_PROVIDER_REGISTRY.get(request.POST.get(PROVIDER_SESSION_KEY))
    if provider is None:
        return WizardError(
            message=_("Please select an email provider to continue."),
            title=_("Selection required"),
            step=0,
        )

    orchestrator.set_session_data(PROVIDER_SESSION_KEY, provider.key)


def _get_settings_initial(orchestrator: BaseStateOrchestrator) -> dict:
    settings = orchestrator.get_session_data(SETTINGS_SESSION_KEY)
    return settings if isinstance(settings, dict) else {}


def get_settings_context(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    provider = EMAIL_PROVIDER_REGISTRY.get(
        orchestrator.get_session_data(PROVIDER_SESSION_KEY)
    )
    initial = {}
    if provider is not None:
        initial.update(provider.initial)
    initial.update(_get_settings_initial(orchestrator))
    form = EmailAccountSettingsForm(
        provider=provider,
        initial=initial,
    )
    return {
        "form": form,
        "provider": provider.key if provider else "",
        "provider_label": provider.name if provider else "",
        "provider_definition": provider,
    }


def process_settings(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    provider = EMAIL_PROVIDER_REGISTRY.get(
        orchestrator.get_session_data(PROVIDER_SESSION_KEY)
    )
    if provider is None:
        return WizardError(
            message=_("Please select an email provider first."),
            title=_("Provider required"),
            step=0,
        )

    form = EmailAccountSettingsForm(
        data=request.POST,
        provider=provider,
        initial=_get_settings_initial(orchestrator),
    )
    if not form.is_valid():
        first_error = next(iter(form.errors.values()))[0] if form.errors else _("Please review the form.")
        return WizardError(
            message=first_error,
            title=_("Account details need attention"),
            step=1,
        )

    cleaned_data = form.cleaned_data.copy()
    for field_name in EmailAccount.SECRET_FIELDS:
        if cleaned_data.get(field_name):
            cleaned_data[field_name] = encrypt_email_secret(cleaned_data[field_name])

    orchestrator.set_session_data(SETTINGS_SESSION_KEY, cleaned_data)


@router.register(
    path="create",
    route_type="model",
    name="Create {model}",
    url_name="add",
    description="Create a new email account",
    models=EmailAccount,
    override=True,
)
class CreateEmailAccountView(WizardMixin, BaseBloomerpView, TemplateView):
    model = EmailAccount
    template_name = "views/base_wizard.html"
    session_key = CREATE_EMAIL_ACCOUNT_SESSION_KEY

    def has_permission(self):
        manager = UserPolicyManager(self.request.user)
        return manager.has_global_permission(
            self.model,
            BloomerpPermission.ADD
        )

    def normalize_step_index(self, step: int) -> int:
        if (
            step > 0
            and EMAIL_PROVIDER_REGISTRY.get(
                self.orchestrator.get_session_data(PROVIDER_SESSION_KEY)
            )
            is None
        ):
            return 0
        return super().normalize_step_index(step)

    def get_step(self, step: int) -> WizardStep | None:
        if step == 0:
            return WizardStep(
                name=_("Select provider"),
                template_name="views/emails/create_email_account/select_provider.html",
                description=_("Choose the type of email account you want to connect."),
                context_func=get_provider_context,
                process_func=process_provider,
            )

        if step == 1:
            return WizardStep(
                name=_("Configure account"),
                template_name="views/emails/create_email_account/configure_account.html",
                description=_("Enter the connection details for this mailbox."),
                context_func=get_settings_context,
                process_func=process_settings,
            )

        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if context.get("step_index") == 1:
            context["wizard_submit_label"] = _("Create account")
        return context

    def done(self):
        payload = self.orchestrator.get_all_session_data()
        provider = EMAIL_PROVIDER_REGISTRY.get(payload.get(PROVIDER_SESSION_KEY))
        settings = payload.get(SETTINGS_SESSION_KEY) or {}

        if provider is None or not isinstance(settings, dict):
            return WizardError(
                message=_("The wizard data is incomplete. Please review the account details."),
                title=_("Incomplete setup"),
                step=0,
            )
        
        try:
            with transaction.atomic():
                email_account = EmailAccount(
                    provider=provider.key,
                    status=EmailAccount.Status.ACTIVE,
                    created_by=self.request.user,
                    updated_by=self.request.user,
                    **settings,
                )
                email_account.save()
                email_account.mailboxes = get_mailboxes_for_account(email_account)
                email_account.save(update_fields=["mailboxes", "datetime_updated"])
        except Exception as exc:
            return WizardError(
                message=str(exc),
                title=_("Mailbox connection failed"),
                step=1,
            )
            

        self.add_message(
            text=_("Email account '%(account)s' created successfully.") % {"account": email_account},
            type="success",
        )
        return None
