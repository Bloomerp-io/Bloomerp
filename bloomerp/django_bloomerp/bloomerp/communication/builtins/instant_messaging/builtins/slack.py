"""Draft Slack transport boundaries; bot and user authorizations remain distinct."""

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
    IMRecipientPage,
)


class SlackConnectionConfiguration(IMConnectionConfiguration):
    """Typed setup fields for the slack connection wizard."""

    workspace_id: str = Field(min_length=1, max_length=255, title="Workspace ID")
    bot_token: SecretStr = Field(min_length=1, title="Bot token")
    signing_secret: SecretStr = Field(default=SecretStr(""), title="Signing secret")

    def external_account_id(self) -> str:
        """Use the configured remote account identifier."""
        return self.workspace_id


class SlackAdapter(BaseIMAdapter):
    """Bind OAuth access to a workspace and explicit bot or user sending identity.

    The provider directory supplies opaque user/channel IDs, not CRM contacts.
    Directory visibility is not permission to read or send in every channel.
    Preserve Slack message timestamps as strings; never convert them to floats.
    """

    provider_key = "slack"

    def validate_connection(self) -> IMConnectionValidation:
        """Keep the draft unavailable until token identity and scopes are checked."""
        return IMConnectionValidation(
            valid=False,
            capabilities=IMCapabilities(),
            issues=("Slack OAuth and connection validation are not implemented yet.",),
        )

    def discover_recipients(
        self, query: str, *, cursor: str | None = None, limit: int = 25
    ) -> IMRecipientPage:
        """Reserve paginated workspace-user and authorized-channel discovery.

        Implement directory listing/cache filtering rather than assuming Slack
        provides a universal free-text recipient search endpoint.
        """
        raise IMAdapterNotReady("Slack recipient discovery is not implemented yet.")

    def format_message(self, message: IMOutboundMessage) -> str:
        """Translate sanitized editor content into slack message text."""
        from html import escape

        from ..content import format_content

        return format_content(message.body_html or escape(message.body), "slack")

    def send_message(self, message: IMOutboundMessage) -> IMDeliveryResult:
        """Reserve opening/resuming DMs and sending to authorized channel/thread IDs.

        A native thread root maps separately from a quoted reference. Do not
        silently turn a quote into a thread or impersonate another workspace user.
        """
        raise IMAdapterNotReady("Slack message transport is not implemented yet.")

    def receive_events(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[IMProviderEvent, ...]:
        """Reserve signed request verification, replay checks and event normalization.

        Resolve the workspace to this installation and distinguish callback
        retries from new events. Ignore or reconcile our own outbound echoes.
        """
        raise IMAdapterNotReady("Slack webhook verification is not implemented yet.")


from ..definition import IMSelectionStep
from django.utils.translation import gettext_lazy as _

SLACK_IM_PROVIDER = IMProviderDefinition(
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
    key="slack",
    config_schema=SlackConnectionConfiguration,
    display_name="Slack",
    icon="fa-brands fa-slack",
    address_field="username",
    adapter_class=SlackAdapter,
    description="Workspace messaging with explicit bot or user authorization.",
    auth_mode="oauth",
    planned_capabilities=IMCapabilities(groups=True, threads=True, directory="remote"),
)
