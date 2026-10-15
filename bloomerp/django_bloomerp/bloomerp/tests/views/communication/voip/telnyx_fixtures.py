"""Real Ed25519 signatures and existing line permissions for Telnyx request scenarios."""

import base64
import time
from typing import Any
from unittest.mock import patch
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bloomerp.communication.builtins.voip.builtins.telnyx import TelnyxAdapter
from bloomerp.communication.builtins.voip.controller import VoIPController, adapter_for
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
)
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber
from bloomerp.tests.base import RequestScenario
from bloomerp.tests.models.communication.voip.fixtures import VoIPFixtures


class TelnyxFixtures(VoIPFixtures):
    """Keep real carrier dispatch, authorization, signing and persistence in endpoint tests."""

    def prepare_telnyx(self) -> None:
        """Configure an isolated Telnyx application on the shared permission fixture."""
        self.prepare_voip()
        self.private_key = Ed25519PrivateKey.generate()
        self.connection = VoIPConnection(
            name="Telnyx",
            provider="telnyx",
            external_account_id="telnyx-account",
            status="active",
            created_by=self.admin_user,
        )
        self.connection.settings = {
            "application_id": "123",
            "credential_connection_id": "456",
            "sip_subdomain": "bloomerp-test",
            "public_url": "https://example.test",
            "browser_calling": True,
            "public_key": base64.b64encode(
                self.private_key.public_key().public_bytes_raw()
            ).decode(),
        }
        self.connection.set_credentials({"api_key": "never-expose-this"})
        self.connection.save()
        self.number = VoIPNumber.objects.create(
            connection=self.connection,
            number="+32470000001",
            provider_number_id="telnyx-number",
            supports_sms=False,
            supports_voice=True,
        )
        self.number.assigned_users.add(self.normal_user)
        self.chat = IMConversation.objects.create(
            provider_key="phone",
            voip_number=self.number,
            phone_address=self.identity.address,
        )
        self.member = IMConversationParticipant.objects.create(
            conversation=self.chat, user=self.normal_user
        )
        self.remote_member = IMConversationParticipant.objects.create(
            conversation=self.chat, identity=self.identity
        )
        self.enterContext(
            patch.object(
                TelnyxAdapter,
                "credentials_for_identities",
                return_value=[{"sip_username": "gencredStaff"}],
            )
        )

    def sign(
        self, scenario: RequestScenario, data: dict[str, Any], *, age: int = 0
    ) -> None:
        """Sign exactly the form-encoded bytes sent through the real webhook route."""
        stamp = str(int(time.time()) - age)
        body = urlencode(data)
        scenario.data = body
        scenario.content_type = "application/x-www-form-urlencoded"
        scenario.view_kwargs = {"connection_id": self.connection.pk}
        scenario.headers = {
            "telnyx-timestamp": stamp,
            "telnyx-signature-ed25519": base64.b64encode(
                self.private_key.sign(stamp.encode() + b"|" + body.encode())
            ).decode(),
        }

    def incoming_data(self) -> dict[str, str]:
        """Describe an inbound call belonging to the configured application and number."""
        return {
            "AccountSid": "telnyx-account",
            "ConnectionId": "123",
            "CallSid": "v3:incoming",
            "From": self.identity.address,
            "To": self.number.number,
            "CallStatus": "ringing",
            "SequenceNumber": "1",
        }

    def incoming(self, scenario: RequestScenario) -> None:
        """Prepare an authenticated incoming telephone call."""
        self.prepare_telnyx()
        self.sign(scenario, self.incoming_data())

    def outgoing(self, scenario: RequestScenario) -> None:
        """Prepare an authorized reservation routed through the application SIP domain."""
        self.prepare_telnyx()
        self.call = VoIPController(self.normal_user).prepare_call(
            self.chat.pk, "telnyx-reservation"
        )
        reference = adapter_for(self.connection).browser_call_reference(self.call.pk)
        self.sign(
            scenario,
            {
                **self.incoming_data(),
                "CallSid": "v3:outgoing",
                "To": reference,
                "ToSipUri": f"{reference}@bloomerp-test.sip.telnyx.com",
            },
        )

    def unsigned(self, scenario: RequestScenario) -> None:
        """Reject a forged event before any persistence or routing occurs."""
        self.incoming(scenario)
        scenario.headers = {}

    def stale(self, scenario: RequestScenario) -> None:
        """Use a genuine signature outside the accepted replay window."""
        self.prepare_telnyx()
        self.sign(scenario, self.incoming_data(), age=601)

    def wrong_application(self, scenario: RequestScenario) -> None:
        """Reject a valid account signature for another instance application."""
        self.prepare_telnyx()
        self.sign(scenario, {**self.incoming_data(), "ConnectionId": "999"})

    def revoked(self, scenario: RequestScenario) -> None:
        """Revoke line usage after signing the outgoing reservation."""
        self.outgoing(scenario)
        self.number.assigned_users.clear()

    def tampered(self, scenario: RequestScenario) -> None:
        """A valid carrier signature must not authorize an unsigned reservation."""
        self.prepare_telnyx()
        self.sign(
            scenario,
            {**self.incoming_data(), "To": "sip:forged@bloomerp-test.sip.telnyx.com"},
        )

    def replay(self, scenario: RequestScenario) -> None:
        """Deliver an incoming request twice to exercise idempotent call projection."""
        self.incoming(scenario)
        response = self.client.post(
            self.get_endpoint(self.view_name, scenario.view_kwargs),
            scenario.data,
            content_type=scenario.content_type,
            headers=scenario.headers,
        )
        self.assertEqual(response.status_code, 200)
