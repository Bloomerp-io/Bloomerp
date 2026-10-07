from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Type

from django.template.loader import render_to_string

from bloomerp.communication.emails.base_adapter import BaseEmailAdapter
from bloomerp.communication.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.utils.base_type_definition import BaseTypeDefinition

class EmailSyncMode(Enum):
    POLLING = "polling"
    PUSH = "push"

    @property
    def label(self) -> str:
        return self.value.title()


@dataclass(frozen=True)
class EmailSyncCapability:
    default_mode: EmailSyncMode = EmailSyncMode.POLLING
    default_poll_interval_minutes : int = 5 # Default polling interval in minutes (5 minutes)
    supported_modes : list[EmailSyncMode] = field(default_factory=lambda: [EmailSyncMode.POLLING,])
    

@dataclass(frozen=True)
class EmailProviderDefinition:
    """
    A dataclass that defines the structure of an email provider.
    """
    key: str # Unique identifier for the email provider
    name: str # Human-readable name of the email provider
    description: str # A brief description of the email provider
    icon: str # Font Awesome icon class for the email provider
    adapter_class: Type[BaseEmailAdapter]
    fields: list[str] = field(default_factory=list) # Fields shown when setting up this provider
    required_fields: list[str] = field(default_factory=list) # Fields required to create this provider
    initial: dict[str, Any] = field(default_factory=dict) # Initial values for provider setup fields
    setup_instructions: str | None = None # Optional setup instructions for the email provider
    sync_capabilities: EmailSyncCapability = field(default_factory=EmailSyncCapability)

class EmailProvider(BaseTypeDefinition):
    # OUTLOOK = EmailProviderDefinition(
    #     key="outlook",
    #     name="Outlook",
    #     description="Connect a Microsoft 365 or Outlook mailbox.",
    #     icon="fa-brands fa-microsoft",
    #     fields=[
    #         "name",
    #         "email_address",
    #         "oauth_client_id",
    #         "oauth_client_secret",
    #         "oauth_tenant_id",
    #         "oauth_scopes",
    #     ],
    #     required_fields=[
    #         "email_address",
    #         "oauth_client_id",
    #         "oauth_client_secret",
    #     ],
    #     initial={
    #         "oauth_scopes": "offline_access Mail.ReadWrite Mail.Send",
    #     },
    #     setup_instructions=render_to_string("models/email_account/provider_instructions/outlook.html"),
    #     adapter_class=BaseEmailAdapter, # Replace with the actual adapter class for Outlook
    # )

    # GOOGLE = EmailProviderDefinition(
    #     key="google",
    #     name="Google",
    #     description="Connect a Gmail or Google Workspace mailbox.",
    #     icon="fa-brands fa-google",
    #     fields=[
    #         "name",
    #         "email_address",
    #         "oauth_client_id",
    #         "oauth_client_secret",
    #         "oauth_tenant_id",
    #         "oauth_scopes",
    #     ],
    #     required_fields=[
    #         "email_address",
    #         "oauth_client_id",
    #         "oauth_client_secret",
    #     ],
    #     initial={
    #         "oauth_scopes": "https://mail.google.com/",
    #     },
    #     setup_instructions=render_to_string("models/email_account/provider_instructions/google.html"),
    #     adapter_class=BaseEmailAdapter, # Replace with the actual adapter class for Google
    # )

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
        setup_instructions=render_to_string("models/email_account/provider_instructions/imap.html"),
        adapter_class=ImapSmtpAdapter,
        sync_capabilities=EmailSyncCapability(
            default_mode=EmailSyncMode.POLLING,
            supported_modes=[
                EmailSyncMode.POLLING,
            ],
            default_poll_interval_minutes=5,
        )
    )

    # OTHER = EmailProviderDefinition(
    #     key="other",
    #     name="Other",
    #     description="Use custom mail server settings for another provider.",
    #     icon="fa-solid fa-at",
    #     fields=[
    #         "name",
    #         "email_address",
    #         "username",
    #         "password",
    #         "imap_host",
    #         "imap_port",
    #         "imap_security",
    #         "smtp_host",
    #         "smtp_port",
    #         "smtp_security",
    #     ],
    #     required_fields=[
    #         "email_address",
    #         "imap_host",
    #         "imap_port",
    #         "smtp_host",
    #         "smtp_port",
    #     ],
    #     setup_instructions=render_to_string("models/email_account/provider_instructions/other.html"),
    #     adapter_class=BaseEmailAdapter, # Replace with the actual adapter class for Other
    # )

    
