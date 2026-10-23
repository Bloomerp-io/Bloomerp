from __future__ import annotations

from typing import Any, ClassVar

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.communication.builtins.emails.email_providers import (
    EmailProviderDefinition,
)
from bloomerp.communication.builtins.emails.mailboxes import (
    merge_mailboxes,
    normalize_mailboxes,
)
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.utils.crypto import encrypt_email_secret
from bloomerp.form_fields.mailbox_settings_field import MailboxSettingsField
from bloomerp.form_fields.mapping_field import MappingField
from bloomerp.models.communication import EmailAccount
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.wizard_mixin import (
    BaseStateOrchestrator,
    WizardError,
    WizardMixin,
    WizardStep,
)

CREATE_EMAIL_ACCOUNT_SESSION_KEY = "email_account_create_wizard"
PROVIDER_SESSION_KEY = "provider"
SETTINGS_SESSION_KEY = "settings"
MAILBOXES_SESSION_KEY = "mailboxes"


class EmailAccountSettingsForm(forms.ModelForm):
    set_as_default = forms.BooleanField(
        required=False, label=_("Use as my default email account")
    )

    class Meta:
        model = EmailAccount
        fields: ClassVar[list[str]] = [
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
            "smtp_envelope_sender",
            "save_sent_emails",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
            "oauth_scopes",
        ]
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "password": forms.PasswordInput(render_value=False),
            "oauth_client_secret": forms.PasswordInput(render_value=False),
            "oauth_scopes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(
        self, *args: Any, provider: EmailProviderDefinition | str, **kwargs: Any
    ) -> None:
        """Build provider-specific connection fields and the default sender option."""
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

        self.fields["save_sent_emails"].widget.attrs["class"] = (
            "checkbox checkbox-primary"
        )
        self.fields["set_as_default"].widget.attrs["class"] = (
            "checkbox checkbox-primary"
        )

        self.fields["name"].required = False
        self.fields["name"].widget.attrs.setdefault(
            "placeholder", _("Accounting inbox")
        )
        self.fields["email_address"].widget.attrs.setdefault(
            "placeholder", _("name@example.com")
        )
        self.fields["username"].required = False
        self.fields["username"].widget.attrs.setdefault(
            "placeholder", _("Defaults to email address")
        )

    def _apply_provider_fields(self) -> None:
        """Keep only provider fields plus the independent sender preference."""
        if self.provider is None:
            self.fields.clear()
            return

        allowed_fields = self.provider.fields
        required_fields = set(self.provider.required_fields)
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = not (
                    field_name in EmailAccount.SECRET_FIELDS
                    and not self.instance._state.adding
                    and bool(getattr(self.instance, field_name))
                )

        for field_name in list(self.fields):
            if field_name not in allowed_fields and field_name != "set_as_default":
                self.fields.pop(field_name)

    def clean(self) -> dict[str, Any]:
        """Retain existing secrets when a reconfiguration leaves password inputs blank."""
        cleaned_data = super().clean()
        email_address = cleaned_data.get("email_address")
        if (
            email_address
            and not cleaned_data.get("username")
            and "username" in self.fields
        ):
            cleaned_data["username"] = email_address
        if not self.instance._state.adding:
            for name in EmailAccount.SECRET_FIELDS:
                if name in self.fields and not cleaned_data.get(name):
                    cleaned_data[name] = getattr(self.instance, name)
        return cleaned_data


def get_provider_context(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Present available providers and the current wizard selection."""
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


def process_provider(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Validate the selected provider before advancing to connection settings."""
    provider = EMAIL_PROVIDER_REGISTRY.get(request.POST.get(PROVIDER_SESSION_KEY))
    if provider is None:
        return WizardError(
            message=_("Please select an email provider to continue."),
            title=_("Selection required"),
            step=0,
        )

    orchestrator.set_session_data(PROVIDER_SESSION_KEY, provider.key)


def _get_settings_initial(orchestrator: BaseStateOrchestrator) -> dict[str, Any]:
    """Return the connection settings retained by this wizard."""
    settings = orchestrator.get_session_data(SETTINGS_SESSION_KEY)
    return settings if isinstance(settings, dict) else {}


def get_settings_context(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Render editable connection settings without exposing stored secrets."""
    provider = EMAIL_PROVIDER_REGISTRY.get(
        orchestrator.get_session_data(PROVIDER_SESSION_KEY)
    )
    initial = {}
    if provider is not None:
        initial.update(provider.initial)
    initial.update(_get_settings_initial(orchestrator))
    form = EmailAccountSettingsForm(
        provider=provider,
        instance=view.get_account(),
        initial=initial,
    )
    callback_uri = ""
    if provider is not None and provider.authorization is not None:
        from bloomerp.communication.builtins.emails.authorization import (
            authorization_callback_uri,
        )

        try:
            callback_uri = authorization_callback_uri(request)
        except ValidationError:
            pass
    return {
        "form": form,
        "provider": provider.key if provider else "",
        "provider_label": provider.name if provider else "",
        "provider_definition": provider,
        "authorization_callback_uri": callback_uri,
    }


def process_settings(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | HttpResponse | None:
    """Validate the connection and discover mailboxes before presenting their mapping."""
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
        instance=view.get_account(),
        initial=_get_settings_initial(orchestrator),
    )
    if not form.is_valid():
        first_error = (
            next(iter(form.errors.values()))[0]
            if form.errors
            else _("Please review the form.")
        )
        return WizardError(
            message=first_error,
            title=_("Account details need attention"),
            step=1,
        )

    cleaned_data = {**provider.initial, **form.cleaned_data}
    for field_name in EmailAccount.SECRET_FIELDS:
        if cleaned_data.get(field_name):
            cleaned_data[field_name] = encrypt_email_secret(cleaned_data[field_name])

    orchestrator.set_session_data(SETTINGS_SESSION_KEY, cleaned_data)
    orchestrator.set_session_data(MAILBOXES_SESSION_KEY, None)
    orchestrator.set_session_data("authorization_complete", None)
    account = form.instance
    for name, value in cleaned_data.items():
        if name != "set_as_default":
            setattr(account, name, value)
    try:
        if provider.authorization is not None:
            from bloomerp.communication.builtins.emails.authorization import (
                begin_authorization,
            )

            original = view.get_account()
            if original is not None:
                original = EmailAccount.objects.get(pk=original.pk)
            return begin_authorization(
                request,
                provider=provider,
                candidate=account,
                account=original,
                wizard_key=view.session_key,
                account_settings=cleaned_data,
            )
        adapter = provider.adapter_class(account)
        try:
            names = adapter.validate_connection()
            defaults = (
                provider.mailbox_defaults(adapter) if provider.mailbox_defaults else {}
            )
            mapping = merge_mailboxes(
                names, normalize_mailboxes(account.mailboxes), provider_defaults=defaults
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
    except ValidationError as exc:
        return WizardError(
            message="; ".join(exc.messages), title=_("Email connection failed"), step=1
        )
    except Exception:  # noqa: BLE001 -- arbitrary transport errors can contain credentials.
        return WizardError(
            message=_(
                "The email provider could not complete setup. Check its configuration and try again."
            ),
            title=_("Email connection failed"),
            step=1,
        )
    orchestrator.set_session_data(MAILBOXES_SESSION_KEY, mapping)


class EmailAccountMailboxesForm(forms.Form):
    """Map each discovered mailbox to its label, roles and color."""

    def __init__(self, *args: Any, mailboxes: dict[str, Any], **kwargs: Any) -> None:
        """Keep provider mailbox keys fixed while allowing their settings to change."""
        super().__init__(*args, **kwargs)
        self.mailboxes = mailboxes
        self.fields["mailboxes"] = MappingField(
            left=[(name, name) for name in mailboxes],
            left_widget=forms.TextInput(attrs={"readonly": True}),
            right_field=MailboxSettingsField(),
            allow_adding_groups=False,
            required=bool(mailboxes),
            initial=mailboxes,
            label=_("Mailboxes"),
        )

        self.fields["mailboxes"].widget.template_name = "widgets/mailbox_mapping.html"

    def clean_mailboxes(self) -> dict[str, Any]:
        """Reject missing or forged mailbox keys and ambiguous role selections."""
        value = self.cleaned_data["mailboxes"]
        if set(value) != set(self.mailboxes):
            raise ValidationError(_("Configure each discovered mailbox exactly once."))
        return normalize_mailboxes(value)


def get_mailboxes_context(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> dict[str, Any]:
    """Render the final mapping step, retaining invalid submitted values for correction."""
    return {
        "form": getattr(view, "mailbox_form", None)
        or EmailAccountMailboxesForm(
            mailboxes=orchestrator.get_session_data(MAILBOXES_SESSION_KEY) or {},
        )
    }


def process_mailboxes(
    request: HttpRequest,
    view: CRUDEmailAccountMixin,
    orchestrator: BaseStateOrchestrator,
) -> WizardError | None:
    """Validate and retain mailbox settings before persisting the email account."""
    form = EmailAccountMailboxesForm(
        request.POST,
        mailboxes=orchestrator.get_session_data(MAILBOXES_SESSION_KEY) or {},
    )
    view.mailbox_form = form
    if not form.is_valid():
        return WizardError(message=_("Please review the mailbox mapping."), step=2)
    orchestrator.set_session_data(MAILBOXES_SESSION_KEY, form.cleaned_data["mailboxes"])


class CRUDEmailAccountMixin(WizardMixin):
    """Share provider, connection and mailbox steps across account creation and editing."""

    model = EmailAccount
    template_name = "views/base_wizard.html"
    session_key = CREATE_EMAIL_ACCOUNT_SESSION_KEY

    def get_account(self) -> EmailAccount | None:
        """Return no existing account during creation; reconfiguration overrides this hook."""
        return None

    def normalize_step_index(self, step: int) -> int:
        """Prevent navigation past incomplete provider and connection steps."""
        if (
            step > 1
            and self.orchestrator.get_session_data(MAILBOXES_SESSION_KEY) is None
        ):
            step = 1
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
        """Define the shared provider, connection and mailbox-mapping steps."""
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

        if step == 2:
            return WizardStep(
                name=_("Map mailboxes"),
                template_name="views/emails/create_email_account/map_mailboxes.html",
                description=_(
                    "Choose labels, a main folder, a Sent folder and optional icon colors."
                ),
                context_func=get_mailboxes_context,
                process_func=process_mailboxes,
            )
        return None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Label the final step according to creation or reconfiguration."""
        context = super().get_context_data(**kwargs)
        provider = EMAIL_PROVIDER_REGISTRY.get(
            self.orchestrator.get_session_data(PROVIDER_SESSION_KEY)
        )
        if (
            context.get("step_index") == 1
            and provider is not None
            and provider.authorization is not None
        ):
            context["wizard_submit_label"] = provider.authorization.label
            context["can_disconnect"] = bool(self.get_account())
        if context.get("step_index") == 2:
            context["wizard_submit_label"] = (
                _("Save account") if self.get_account() else _("Create account")
            )
        return context

    def done(self) -> HttpResponse | WizardError | None:
        """Save a verified account and its validated mailbox mapping atomically."""
        payload = self.orchestrator.get_all_session_data()
        provider = EMAIL_PROVIDER_REGISTRY.get(payload.get(PROVIDER_SESSION_KEY))
        settings = payload.get(SETTINGS_SESSION_KEY) or {}

        if provider is None or not isinstance(settings, dict):
            return WizardError(
                message=_(
                    "The wizard data is incomplete. Please review the account details."
                ),
                title=_("Incomplete setup"),
                step=0,
            )

        settings = dict(settings)
        if provider.authorization is not None and not payload.get(
            "authorization_complete"
        ):
            return WizardError(
                message=_("Connect the account before saving its mailbox mapping."),
                step=1,
            )
        if provider.authorization is not None:
            expires = parse_datetime(payload.get("authorization_expires", ""))
            if expires is None or expires <= timezone.now():
                return WizardError(
                    message=_(
                        "Authorization setup expired. Connect the account again."
                    ),
                    step=1,
                )
        if isinstance(settings.get("token_expires_at"), str):
            settings["token_expires_at"] = parse_datetime(settings["token_expires_at"])
        set_as_default = settings.pop("set_as_default", False)
        try:
            email_account = self.get_account() or EmailAccount(
                created_by=self.request.user
            )
            provider_changed = email_account.provider != provider.key
            email_account.provider = provider.key
            email_account.updated_by = self.request.user
            for name, value in settings.items():
                setattr(email_account, name, value)
            if provider_changed:
                email_account.sync_cursor = {}
                if provider.authorization is None:
                    email_account.access_token = ""
                    email_account.refresh_token = ""
                    email_account.token_expires_at = None
                    email_account.extra_settings = {}
            if provider.authorization is not None:
                email_account.sync_enabled = True
            email_account.mailboxes = normalize_mailboxes(
                payload.get(MAILBOXES_SESSION_KEY, {})
            )
            email_account.full_clean()
            email_account.mark_validated(save=False)
            with transaction.atomic():
                if (
                    provider.authorization is not None
                    and not email_account._state.adding
                ):
                    from bloomerp.communication.builtins.emails.authorization import (
                        account_configuration_fingerprint,
                    )

                    current = EmailAccount.objects.select_for_update().get(
                        pk=email_account.pk
                    )
                    if payload.get(
                        "authorization_configuration"
                    ) != account_configuration_fingerprint(current):
                        raise ValidationError(
                            _(
                                "The account changed during setup. Connect again before saving."
                            )
                        )
                if email_account._state.adding:
                    email_account.save()
                else:
                    update_fields = {
                        *settings, "provider", "mailboxes", "status",
                        "validation_error", "last_validated_at", "updated_by",
                        "datetime_updated",
                    }
                    if provider.authorization is not None:
                        email_account.next_sync_at = timezone.now()
                        update_fields.update({"sync_enabled", "next_sync_at"})
                    if provider_changed:
                        update_fields.update({"sync_cursor", "access_token", "refresh_token", "token_expires_at", "extra_settings"})
                    email_account.save(update_fields=update_fields)
                if set_as_default:
                    self.request.user.default_email_account = email_account
                    self.request.user.save(update_fields=["default_email_account"])
        except ValidationError as exc:
            return WizardError(
                message="; ".join(exc.messages),
                title=_("Email connection failed"),
                step=1,
            )
        except Exception:  # noqa: BLE001 -- persistence diagnostics must not expose account secrets.
            return WizardError(
                message=_("The email account could not be saved. Please try again."),
                title=_("Email connection failed"),
                step=1,
            )

        self.add_message(
            text=_("Email account '%(account)s' saved successfully.")
            % {"account": email_account},
            type="success",
        )
        return None


@router.register(
    path="create",
    route_type="model",
    name="Create {model}",
    url_name="add",
    description="Create a new email account",
    models=EmailAccount,
    override=True,
)
class CreateEmailAccountView(CRUDEmailAccountMixin, BaseBloomerpView, TemplateView):
    """Create an email account through the shared configuration wizard."""

    def has_permission(self) -> bool:
        """Require model-level permission to create an email account."""
        manager = UserPolicyManager(self.request.user)
        return manager.has_global_permission(self.model, BloomerpPermission.ADD)
