"""Built-in email providers; contracts live in the neutral definition module."""

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from bloomerp.utils.base_type_definition import BaseTypeDefinition

from .provider_definition import (
    EmailAuthorizationDefinition,
    EmailProviderDefinition,
    EmailSyncCapability,
    EmailSyncMode,
)
from .providers.imap_smtp import ImapSmtpAdapter
from .providers.outlook import OutlookAdapter


class EmailProvider(BaseTypeDefinition):
    """Register bundled transports through the same extension contract as custom providers."""

    OUTLOOK = EmailProviderDefinition(
        key="outlook",
        name="Microsoft 365 / Outlook",
        description=_(
            "Connect a mailbox with delegated Microsoft Graph authorization."
        ),
        icon="fa-brands fa-microsoft",
        adapter_class=OutlookAdapter,
        fields=[
            "name",
            "email_address",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
        ],
        required_fields=[
            "email_address",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
        ],
        initial={"oauth_scopes": "offline_access User.Read Mail.ReadWrite Mail.Send"},
        setup_instructions=render_to_string(
            "models/email_account/provider_instructions/outlook.html"
        ),
        authorization=EmailAuthorizationDefinition(
            prepare=OutlookAdapter.prepare_authorization,
            start=OutlookAdapter.get_authorization_url,
            complete=OutlookAdapter.complete_authorization,
            label=_("Connect Microsoft account"),
        ),
        mailbox_defaults=OutlookAdapter.mailbox_defaults,
    )

    IMAP = EmailProviderDefinition(
        key="imap",
        name="IMAP / SMTP",
        description="Connect a mailbox with incoming and outgoing server credentials.",
        icon="fa-solid fa-envelope-open-text",
        fields=[
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
        ],
        required_fields=[
            "email_address",
            "imap_host",
            "imap_port",
            "smtp_host",
            "smtp_port",
        ],
        setup_instructions=render_to_string(
            "models/email_account/provider_instructions/imap.html"
        ),
        adapter_class=ImapSmtpAdapter,
        sync_capabilities=EmailSyncCapability(
            default_mode=EmailSyncMode.POLLING,
            supported_modes=[
                EmailSyncMode.POLLING,
            ],
            default_poll_interval_minutes=5,
        ),
    )
