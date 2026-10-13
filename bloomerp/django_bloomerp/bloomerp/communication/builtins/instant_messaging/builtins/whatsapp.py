"""Draft WhatsApp transport boundaries; no provider HTTP calls are enabled."""

from typing import Mapping

from pydantic import Field, SecretStr

from ..definition import (
    BaseIMAdapter,
    IMAdapterNotReady,
    IMCapabilities,
    IMConnectionConfiguration,
    IMConnectionValidation,
    IMDeliveryResult,
    IMOutboundMessage,
    IMProviderDefinition,
    IMProviderEvent,
    IMUnsupportedOperation,
)


class WhatsAppConnectionConfiguration(IMConnectionConfiguration):
    """Typed setup fields for the whatsapp connection wizard."""

    business_account_id: str = Field(
        pattern=r"^[0-9]+$", max_length=255, title="WhatsApp Business Account ID"
    )
    phone_number_id: str = Field(
        pattern=r"^[0-9]+$", max_length=255, title="Phone number ID"
    )
    access_token: SecretStr = Field(
        min_length=1,
        title="Access token",
        description="Token for your WhatsApp Business account.",
    )
    app_secret: SecretStr = Field(
        default=SecretStr(""),
        title="App secret",
        description="Used to verify incoming webhook signatures.",
    )
    webhook_verify_token: SecretStr = Field(
        default=SecretStr(""),
        title="Webhook verify token",
        description="Shared token for webhook verification.",
    )

    def external_account_id(self) -> str:
        """Use the configured remote account identifier."""
        return self.business_account_id


class WhatsAppAdapter(BaseIMAdapter):
    """Use a business connection and phone endpoint, with optional Coexistence sync.

    Implementation must enforce the active messaging window/template rules,
    retain provider-scoped identities, and reconcile webhook acknowledgments.
    Quoted replies are distinct from Bloomerp threads. Group support must be
    negotiated for the specific API/account rather than inferred from the app.
    """

    provider_key = "whatsapp"

    def validate_connection(self) -> IMConnectionValidation:
        """Keep draft transport unavailable until an authenticated remote check exists."""
        return IMConnectionValidation(
            valid=False,
            capabilities=IMCapabilities(),
            issues=(
                "WhatsApp authorization and connection validation are not implemented yet.",
            ),
        )

    def format_message(self, message: IMOutboundMessage) -> str:
        """Translate sanitized editor content into whatsapp message text."""
        from html import escape

        from bloomerp.utils.rich_text import format_content

        return format_content(message.body_html or escape(message.body), "whatsapp")

    def send_message(self, message: IMOutboundMessage) -> IMDeliveryResult:
        """Reserve text/media/template dispatch and quoted provider-message references.

        Persist provider IDs only on acknowledgment; an ambiguous timeout must
        not be classified as safely retryable without reconciliation.
        """
        raise IMAdapterNotReady("WhatsApp message transport is not implemented yet.")

    def request_contact_sync(self) -> None:
        """Reserve Coexistence synchronization; this is not live address-book search."""
        if self.context.settings.get("coexistence") != "true":
            raise IMUnsupportedOperation(
                "Contact synchronization requires Coexistence."
            )
        raise IMAdapterNotReady(
            "WhatsApp contact synchronization is not implemented yet."
        )

    def receive_events(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[IMProviderEvent, ...]:
        """Reserve signature verification and normalization of messages/status/contact sync.

        Verify the signature using the app signing secret before parsing. Match
        business account and phone endpoint to the receiving connection. Emit
        all events in batched payloads with stable deduplication keys.
        """
        raise IMAdapterNotReady("WhatsApp webhook verification is not implemented yet.")


from ..definition import IMSelectionStep
from django.utils.translation import gettext_lazy as _

WHATSAPP_IM_PROVIDER = IMProviderDefinition(
    selection_steps=(
        IMSelectionStep(
            "connection_id",
            _("Connection"),
            "bloomerp.communication.builtins.instant_messaging.selection.configured_connections",
        ),
        IMSelectionStep(
            "endpoint_id",
            _("Sending endpoint"),
            "bloomerp.communication.builtins.instant_messaging.selection.configured_endpoints",
        ),
        IMSelectionStep(
            "recipient_id",
            _("Recipient"),
            "bloomerp.communication.builtins.instant_messaging.selection.external_recipients",
            searchable=True,
        ),
    ),
    start_handler="bloomerp.communication.builtins.instant_messaging.selection.start_external",
    key="whatsapp",
    config_schema=WhatsAppConnectionConfiguration,
    display_name="WhatsApp",
    icon="fa-brands fa-whatsapp",
    address_field="phone",
    adapter_class=WhatsAppAdapter,
    description="Business messaging through an authorized phone endpoint.",
    auth_mode="embedded_signup",
    planned_capabilities=IMCapabilities(
        quoted_replies=True,
        attachments=True,
        read_receipts=True,
        outbound_templates=True,
        manual_address=True,
    ),
)
