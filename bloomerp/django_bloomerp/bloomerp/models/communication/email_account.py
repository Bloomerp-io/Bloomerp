from django.utils.translation import gettext_lazy as _, gettext_noop
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from bloomerp.communication.utils.crypto import encrypt_email_secret
from bloomerp.communication.utils.crypto import decrypt_email_secret
from bloomerp.communication.emails.email_providers import EmailSyncMode
from bloomerp.communication.emails.registry import (
    EMAIL_PROVIDER_REGISTRY,
    email_provider_choices,
)
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig, DetailViewSettings
from bloomerp.models import BloomerpModel


class EmailAccount(BloomerpModel):
    SECRET_FIELDS = (
        "password",
        "oauth_client_secret",
        "access_token",
        "refresh_token",
    )

    class SecurityMode(models.TextChoices):
        SSL_TLS = "ssl_tls", _("SSL/TLS")
        STARTTLS = "starttls", _("STARTTLS")
        NONE = "none", _("None")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        ERROR = "error", _("Error")

    class Meta:
        db_table = "bloomerp_email_account"
        verbose_name = _("Email Account")
        verbose_name_plural = _("Email Accounts")
        indexes = [
            models.Index(fields=["provider", "status"], name="email_acc_provider_status_idx"),
            models.Index(fields=["email_address"], name="email_acc_address_idx"),
            models.Index(fields=["status", "sync_enabled", "next_sync_at"], name="email_acc_sync_due_idx"),
        ]
    
    bloomerp_config = BloomerpModelConfig(
        module=None,
        api_settings=ApiSettings(enable_auto_generation=False),
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Account"),
                    items=[
                        LayoutItem(id="name"),
                        LayoutItem(id="email_address"),
                        LayoutItem(id="provider"),
                        LayoutItem(id="status"),
                    ]
                ),
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Incoming mail"),
                    items=[
                        LayoutItem(id="imap_host"),
                        LayoutItem(id="imap_port"),
                        LayoutItem(id="imap_security"),
                        LayoutItem(id="username"),
                    ]
                ),
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Outgoing mail"),
                    items=[
                        LayoutItem(id="smtp_host"),
                        LayoutItem(id="smtp_port"),
                        LayoutItem(id="smtp_security"),
                        LayoutItem(id="save_sent_emails"),
                        LayoutItem(id="last_validated_at"),
                    ]
                ),
                LayoutRow(
                    columns=2,
                    title=gettext_noop("Synchronization"),
                    items=[
                        LayoutItem(id="sync_enabled"),
                        LayoutItem(id="sync_mode"),
                        LayoutItem(id="sync_interval_minutes"),
                        LayoutItem(id="next_sync_at"),
                    ]
                )
                ]
            )],
            skip_views=[
                "document_templates",
                "files",
            ]
        ),
    )
    
    name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Name"),
    )
    email_address = models.EmailField(
        max_length=255,
        unique=True,
        verbose_name=_("Email Address"),
    )
    provider = models.CharField(
        max_length=32,
        choices=email_provider_choices,
        default="imap",
        verbose_name=_("Provider"),
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("Status"),
    )
    username = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Username"),
    )
    password = models.TextField(
        blank=True,
        help_text="Encrypted password or app password used for providers that support direct SMTP/IMAP authentication.",
        verbose_name=_("Password"),
    )
    imap_host = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("IMAP Host"),
    )
    imap_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("IMAP Port"),
    )
    imap_security = models.CharField(
        max_length=32,
        choices=SecurityMode.choices,
        default=SecurityMode.SSL_TLS,
        verbose_name=_("IMAP Security"),
    )
    smtp_host = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("SMTP Host"),
    )
    smtp_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("SMTP Port"),
    )
    smtp_security = models.CharField(
        max_length=32,
        choices=SecurityMode.choices,
        default=SecurityMode.STARTTLS,
        verbose_name=_("SMTP Security"),
    )
    save_sent_emails = models.BooleanField(
        default=False,
        verbose_name=_("Save sent emails via IMAP"),
        help_text=_(
            "Save a copy in the server's Sent folder after sending. Enable for providers "
            "such as Neo; leave disabled if your provider already saves sent emails automatically."
        ),
    )
    oauth_client_id = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("OAuth Client ID"),
    )
    oauth_client_secret = models.TextField(
        blank=True,
        help_text="Encrypted OAuth client secret.",
        verbose_name=_("OAuth Client Secret"),
    )
    oauth_tenant_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider tenant, directory, or workspace identifier when applicable.",
        verbose_name=_("OAuth Tenant ID"),
    )
    oauth_scopes = models.TextField(
        blank=True,
        help_text="Space-separated OAuth scopes requested for this account.",
        verbose_name=_("OAuth Scopes"),
    )
    access_token = models.TextField(
        blank=True,
        help_text="Encrypted OAuth access token.",
        verbose_name=_("Access Token"),
    )
    refresh_token = models.TextField(
        blank=True,
        help_text="Encrypted OAuth refresh token.",
        verbose_name=_("Refresh Token"),
    )
    token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Token Expires At"),
    )
    extra_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific settings that do not have dedicated fields yet.",
        verbose_name=_("Extra Settings"),
    )
    # Synchronization fields
    sync_enabled = models.BooleanField(
        default=True,
        help_text="Whether this account should be synchronized automatically.",
        verbose_name=_("Sync Enabled"),
    )
    sync_mode = models.CharField(
        max_length=32,
        choices=[(mode.value, mode.label) for mode in EmailSyncMode],
        blank=True,
        help_text="Synchronization mode for this account. Defaults to the provider's preferred mode.",
        verbose_name=_("Sync Mode"),
    )
    sync_interval_minutes = models.PositiveIntegerField(
        default=5,
        help_text="Polling interval used by providers that synchronize on a schedule.",
        verbose_name=_("Sync Interval Minutes"),
    )
    sync_cursor = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific cursor/state for incremental synchronization.",
        verbose_name=_("Sync Cursor"),
    )
    next_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Next Sync At"),
    )
    last_sync_started_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Last Sync Started At"),
    )
    last_sync_finished_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Last Sync Finished At"),
    )
    sync_locked_until = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Sync Locked Until"),
    )
    last_sync_error = models.TextField(
        blank=True,
        editable=False,
        verbose_name=_("Last Sync Error"),
    )
    last_validated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Last Validated At"),
    )
    validation_error = models.TextField(
        blank=True,
        editable=False,
        verbose_name=_("Validation Error"),
    )
    mailboxes = models.JSONField(
        default=list,
        blank=True,
        help_text="Cached list of folders/mailboxes for this account.",
        verbose_name=_("Mailboxes"),
    )
    
    
    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.email_address
        if not self.username:
            self.username = self.email_address
        self.apply_provider_sync_defaults()
        self.encrypt_secret_fields()
        super().save(*args, **kwargs)

    def apply_provider_sync_defaults(self) -> None:
        provider = EMAIL_PROVIDER_REGISTRY.get(self.provider)
        if provider is None:
            return

        sync_capabilities = provider.sync_capabilities
        if not self.sync_mode:
            self.sync_mode = sync_capabilities.default_mode.value
        if not self.sync_interval_minutes:
            self.sync_interval_minutes = sync_capabilities.default_poll_interval_minutes

    def encrypt_secret_fields(self) -> None:
        for field_name in self.SECRET_FIELDS:
            value = getattr(self, field_name, "")
            if value:
                setattr(self, field_name, encrypt_email_secret(value))

    def set_secret(self, field_name: str, value: str | None) -> None:
        self._validate_secret_field(field_name)
        setattr(self, field_name, encrypt_email_secret(value))

    def get_secret(self, field_name: str) -> str:
        self._validate_secret_field(field_name)
        return decrypt_email_secret(getattr(self, field_name, ""))

    def _validate_secret_field(self, field_name: str) -> None:
        if field_name not in self.SECRET_FIELDS:
            raise ValueError(f"{field_name} is not an encrypted email account secret field.")

    def set_password_secret(self, value: str | None) -> None:
        self.set_secret("password", value)

    def get_password_secret(self) -> str:
        return self.get_secret("password")

    def set_oauth_client_secret(self, value: str | None) -> None:
        self.set_secret("oauth_client_secret", value)

    def get_oauth_client_secret(self) -> str:
        return self.get_secret("oauth_client_secret")

    def set_access_token_secret(self, value: str | None) -> None:
        self.set_secret("access_token", value)

    def get_access_token_secret(self) -> str:
        return self.get_secret("access_token")

    def set_refresh_token_secret(self, value: str | None) -> None:
        self.set_secret("refresh_token", value)

    def get_refresh_token_secret(self) -> str:
        return self.get_secret("refresh_token")

    def clean(self):
        super().clean()
        provider = EMAIL_PROVIDER_REGISTRY.get(self.provider)
        if provider is None:
            raise ValidationError({"provider": "Select a valid email provider."})

        errors = {}
        for field_name in provider.required_fields:
            value = getattr(self, field_name, None)
            if value in (None, "", []):
                errors[field_name] = f"This field is required for {provider.name}."

        sync_mode = self.sync_mode or provider.sync_capabilities.default_mode.value
        supported_modes = [
            supported_mode.value
            for supported_mode in provider.sync_capabilities.supported_modes
        ]
        if sync_mode not in supported_modes:
            errors["sync_mode"] = f"{provider.name} does not support this synchronization mode."

        if errors:
            raise ValidationError(errors)

    def mark_validated(self, save: bool = True) -> None:
        self.status = self.Status.ACTIVE
        self.validation_error = ""
        self.last_validated_at = timezone.now()
        if self.sync_enabled and self.next_sync_at is None:
            self.next_sync_at = timezone.now()
        if save:
            self.save(update_fields=["status", "validation_error", "last_validated_at", "next_sync_at", "datetime_updated"])

    def mark_validation_error(self, error: str, save: bool = True) -> None:
        self.status = self.Status.ERROR
        self.validation_error = error
        if save:
            self.save(update_fields=["status", "validation_error", "datetime_updated"])

    def __str__(self) -> str:
        return self.name or self.email_address
