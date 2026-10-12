"""Twilio REST, signed webhooks and browser Voice SDK authorization."""

from datetime import datetime
from typing import Any
from django.utils.translation import gettext_lazy as _
from pydantic import Field, SecretStr
from twilio.http.http_client import TwilioHttpClient
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from ..definition import (
    BaseVoIPAdapter,
    VoIPCapabilities,
    VoIPCallData,
    VoIPConfiguration,
    VoIPNumberData,
    VoIPProviderDefinition,
)


class TwilioConfiguration(VoIPConfiguration):
    """Describe account authentication and optional browser-calling credentials."""

    account_sid: str = Field(pattern=r"^AC[0-9a-fA-F]{32}$", title=_("Account SID"))
    auth_token: SecretStr = Field(min_length=1, title=_("Auth token"))
    api_key_sid: str = Field(
        default="", pattern=r"^(SK[0-9a-fA-F]{32})?$", title=_("Voice API key SID")
    )
    api_key_secret: SecretStr = Field(
        default=SecretStr(""), title=_("Voice API key secret")
    )
    application_sid: str = Field(
        default="", pattern=r"^(AP[0-9a-fA-F]{32})?$", title=_("TwiML application SID")
    )
    public_url: str = Field(
        pattern=r"^https://[^/?#]+(?:/[^?#]*)?$",
        title=_("Public HTTPS URL"),
        description=_(
            "Public base URL of this Bloomerp instance for Twilio callbacks."
        ),
    )

    def external_account_id(self) -> str:
        """Bind the saved connection to the configured Twilio account."""
        return self.account_sid


class TwilioAdapter(BaseVoIPAdapter):
    """Use the official SDK with bounded HTTP calls and no automatic send retries."""

    provider_key = "twilio"

    def client(self) -> Client:
        """Build an authenticated client without logging credentials or request bodies."""
        return Client(
            self.context.account_id,
            self.context.credentials["auth_token"],
            http_client=TwilioHttpClient(timeout=15, max_retries=0),
        )

    def validate_connection(self) -> VoIPCapabilities:
        """Verify account ownership and optional voice application/key configuration."""
        account = self.client().api.accounts(self.context.account_id).fetch()
        if account.status != "active":
            raise ValueError(_("The Twilio account is not active."))
        browser = bool(
            self.context.settings.get("api_key_sid")
            and self.context.credentials.get("api_key_secret")
            and self.context.settings.get("application_sid")
        )
        if browser:
            voice_client = Client(
                self.context.settings["api_key_sid"],
                self.context.credentials["api_key_secret"],
                account_sid=self.context.account_id,
                http_client=TwilioHttpClient(timeout=15, max_retries=0),
            )
            voice_client.applications(self.context.settings["application_sid"]).fetch()
        return VoIPCapabilities(
            sms=True, voice=True, history_sync=True, browser_calling=browser
        )

    def list_numbers(self) -> tuple[VoIPNumberData, ...]:
        """Retrieve all carrier numbers before reconciling local inventory."""
        return tuple(
            VoIPNumberData(
                n.sid,
                n.phone_number,
                n.friendly_name or "",
                bool(n.capabilities.get("sms")),
                bool(n.capabilities.get("voice")),
            )
            for n in self.client().incoming_phone_numbers.stream()
        )

    def sync_calls(self, since: datetime | None) -> tuple[VoIPCallData, ...]:
        """Read call history with overlap supplied by the synchronization controller."""
        filters: dict[str, Any] = {"start_time_after": since} if since else {}
        return tuple(
            VoIPCallData(
                c.sid,
                c.parent_call_sid or "",
                c.from_ or "",
                c.to or "",
                "inbound" if c.direction == "inbound" else "outbound",
                c.status,
                c.start_time,
                c.end_time,
                int(c.duration or 0),
            )
            for c in self.client().calls.stream(**filters)
        )

    def send_sms(self, sender: str, recipient: str, body: str, callback: str) -> str:
        """Submit one SMS without unsafe retry after ambiguous network failures."""
        return (
            self.client()
            .messages.create(
                from_=sender, to=recipient, body=body, status_callback=callback
            )
            .sid
        )

    def browser_token(self, identity: str) -> str:
        """Issue a ten-minute Voice grant without exposing long-lived secrets."""
        token = AccessToken(
            self.context.account_id,
            self.context.settings["api_key_sid"],
            self.context.credentials["api_key_secret"],
            identity=identity,
            ttl=600,
        )
        token.add_grant(
            VoiceGrant(
                outgoing_application_sid=self.context.settings["application_sid"],
                incoming_allow=True,
            )
        )
        return token.to_jwt()

    def verify_webhook(self, url: str, params: Any, signature: str) -> bool:
        """Validate the exact public URL and all form fields before normalization."""
        return (
            bool(signature)
            and RequestValidator(self.context.credentials["auth_token"]).validate(
                url, params, signature
            )
            and params.get("AccountSid") == self.context.account_id
        )


TWILIO_PROVIDER = VoIPProviderDefinition(
    key="twilio",
    display_name=_("Twilio"),
    icon="fa-solid fa-phone",
    description=_("SMS, browser calls and synchronized call history."),
    config_schema=TwilioConfiguration,
    adapter_class=TwilioAdapter,
)
