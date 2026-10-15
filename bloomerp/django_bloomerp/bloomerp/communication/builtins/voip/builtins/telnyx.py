"""Telnyx inventory, short-lived WebRTC credentials and authenticated TeXML routing."""

import base64
import binascii
import json
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.core import signing
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pydantic import Field, SecretStr

from ..definition import (
    BaseVoIPAdapter,
    VoIPCapabilities,
    VoIPConfiguration,
    VoIPNumberData,
    VoIPProviderDefinition,
)


class TelnyxConfiguration(VoIPConfiguration):
    """Configure a dedicated TeXML application and browser-only credential connection."""

    account_id: str = Field(min_length=1, max_length=128, title=_("Telnyx account ID"))
    api_key: SecretStr = Field(min_length=1, title=_("API v2 key"))
    public_key: str = Field(min_length=1, title=_("Webhook Ed25519 public key"))
    application_id: str = Field(pattern=r"^\d+$", title=_("TeXML application ID"))
    credential_connection_id: str = Field(
        pattern=r"^\d+$", title=_("Browser credential connection ID")
    )
    sip_subdomain: str = Field(
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
        title=_("TeXML SIP subdomain"),
    )
    public_url: str = Field(
        pattern=r"^https://[^/?#]+(?:/[^?#]*)?$", title=_("Public HTTPS URL")
    )

    def external_account_id(self) -> str:
        """Bind signed TeXML callbacks to the configured Telnyx account."""
        return self.account_id


class TelnyxAdapter(BaseVoIPAdapter):
    """Keep Telnyx REST and SIP details behind the carrier adapter contract."""

    provider_key = "telnyx"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        plain: bool = False,
    ) -> Any:
        """Make one bounded API request without retrying ambiguous mutations."""
        response = requests.request(
            method,
            f"https://api.telnyx.com/v2/{path}",
            headers={"Authorization": f"Bearer {self.context.credentials['api_key']}"},
            params=params,
            json=data,
            timeout=15,
        )
        if not response.ok:
            raise ValueError(
                _(
                    "Telnyx rejected the request. Check account access and connection settings."
                )
            )
        return response.text if plain else response.json()

    def pages(self, path: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Retrieve every inventory page before updating local records."""
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request(
                "GET", path, params={**filters, "page[number]": page, "page[size]": 100}
            )
            result.extend(payload["data"])
            if page >= int(payload["meta"]["total_pages"]):
                return result
            page += 1

    def browser_connection(self) -> dict[str, Any]:
        """Reject browser credentials that could dial the PSTN outside application authorization."""
        connection = self.request(
            "GET",
            f"credential_connections/{self.context.settings['credential_connection_id']}",
        )["data"]
        if (
            not connection.get("active")
            or connection.get("outbound", {}).get("outbound_voice_profile_id")
            or connection.get("sip_uri_calling_preference") != "internal"
        ):
            raise ValueError(
                _(
                    "Use an active browser credential connection without an outbound voice profile and with SIP URI calling set to internal. Attach the outbound profile only to the TeXML application."
                )
            )
        return connection

    def validate_connection(self) -> VoIPCapabilities:
        """Validate routing resources before advertising browser audio support."""
        app = self.request(
            "GET", f"texml_applications/{self.context.settings['application_id']}"
        )["data"]
        inbound = app.get("inbound", {})
        if (
            not app.get("active")
            or inbound.get("sip_subdomain") != self.context.settings["sip_subdomain"]
            or inbound.get("sip_subdomain_receive_settings") != "only_my_connections"
        ):
            raise ValueError(
                _(
                    "Activate the TeXML application and configure its SIP subdomain to receive only your connections."
                )
            )
        if not app.get("outbound", {}).get("outbound_voice_profile_id"):
            raise ValueError(
                _("Assign an outbound voice profile to the TeXML application.")
            )
        self.browser_connection()
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.context.settings["public_key"], validate=True)
            )
        except (ValueError, binascii.Error) as error:
            raise ValueError(_("Enter a valid Telnyx Ed25519 public key.")) from error
        return VoIPCapabilities(voice=True, browser_calling=True)

    def list_numbers(self) -> tuple[VoIPNumberData, ...]:
        """Import only purchased numbers assigned to this instance's TeXML application."""
        app = self.context.settings["application_id"]
        numbers = self.pages("phone_numbers", {"filter[connection_id]": app})
        return tuple(
            VoIPNumberData(
                str(item["id"]),
                item["phone_number"],
                item.get("customer_reference") or "",
                False,
                True,
            )
            for item in numbers
            if str(item.get("connection_id")) == app and item.get("status") == "active"
        )

    def callback_url(self, kind: str, **kwargs: Any) -> str:
        """Build provider callbacks from the configured public instance URL."""
        return self.context.settings["public_url"].rstrip("/") + reverse(
            f"voip_{kind}",
            kwargs={"connection_id": self.context.connection_id, **kwargs},
        )

    def verify_request(self, request: HttpRequest, kind: str, **kwargs: Any) -> bool:
        """Verify timestamp and exact raw-body signature before trusting TeXML form data."""
        try:
            stamp = request.headers.get("telnyx-timestamp", "")
            if abs(time.time() - int(stamp)) > 300:
                return False
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.context.settings["public_key"], validate=True)
            )
            signature = base64.b64decode(
                request.headers.get("telnyx-signature-ed25519", ""), validate=True
            )
            key.verify(signature, stamp.encode() + b"|" + request.body)
            return (
                request.POST.get("AccountSid") == self.context.account_id
                and request.POST.get("ConnectionId")
                == self.context.settings["application_id"]
            )
        except (ValueError, binascii.Error, InvalidSignature):
            return False

    def credentials_for(self, identity: str) -> list[dict[str, Any]]:
        """Find this instance actor's current credentials without shared SIP passwords."""
        return self.credentials_for_identities({identity})

    def credentials_for_identities(self, identities: set[str]) -> list[dict[str, Any]]:
        """Resolve assigned recipients in one inventory traversal rather than one call per user."""
        if not identities:
            return []
        resource_id = f"connection:{self.context.settings['credential_connection_id']}"
        filters = {"filter[resource_id]": resource_id}
        if len(identities) == 1:
            filters["filter[name]"] = next(iter(identities))
        return [
            item
            for item in self.pages("telephony_credentials", filters)
            if item.get("name") in identities
            and item.get("resource_id") == resource_id
            and not item.get("expired")
        ]

    def browser_token(self, identity: str) -> str:
        """Issue a token bounded by a ten-minute credential lifetime after current authorization."""
        self.browser_connection()
        existing = self.credentials_for(identity)
        expiry = (timezone.now() + timedelta(minutes=10)).isoformat()
        if existing:
            credential = self.request(
                "PATCH",
                f"telephony_credentials/{existing[0]['id']}",
                data={"expires_at": expiry},
            )["data"]
        else:
            credential = self.request(
                "POST",
                "telephony_credentials",
                data={
                    "connection_id": self.context.settings["credential_connection_id"],
                    "name": identity,
                    "expires_at": expiry,
                },
            )["data"]
        token = self.request(
            "POST", f"telephony_credentials/{credential['id']}/token", plain=True
        )
        return json.dumps(
            {
                "token": token,
                "domain": f"{self.context.settings['sip_subdomain']}.sip.telnyx.com",
            }
        )

    def browser_call_reference(self, call_id: UUID) -> str:
        """Sign the opaque reservation so arbitrary SIP destinations cannot originate paid calls."""
        return signing.TimestampSigner(
            salt=f"telnyx:{self.context.connection_id}", sep="."
        ).sign(call_id.hex)

    def resolve_call_reference(self, reference: str) -> UUID:
        """Accept only a recent reservation issued for this Bloomerp connection."""
        return UUID(
            signing.TimestampSigner(
                salt=f"telnyx:{self.context.connection_id}", sep="."
            ).unsign(reference, max_age=600)
        )


TELNYX_PROVIDER = VoIPProviderDefinition(
    key="telnyx",
    display_name=_("Telnyx"),
    icon="fa-solid fa-phone",
    description=_("Browser voice calls using dashboard-purchased Telnyx numbers."),
    config_schema=TelnyxConfiguration,
    adapter_class=TelnyxAdapter,
    account_id_field="account_id",
    immutable_config_fields=("application_id", "credential_connection_id"),
    browser_driver="telnyx",
    configuration_help=_(
        "Use a dedicated TeXML application with an outbound voice profile, and a separate browser credential connection without an outbound voice profile. Buy numbers in Telnyx, assign them to the TeXML application, then synchronize."
    ),
    callback_help=_(
        "Configure the TeXML application Voice URL and status callback with these URLs using POST. Enable its SIP subdomain for only your connections. SMS and number purchasing are not supported by this integration."
    ),
    callback_labels={
        "voice": _("TeXML Voice URL"),
        "call_status": _("TeXML status callback"),
    },
    webhook_handlers={
        kind: f"bloomerp.communication.builtins.voip.builtins.telnyx_webhooks.{kind}.{kind}"
        for kind in ("voice", "call_status")
    },
    operation_errors=(requests.RequestException, ValueError),
)
