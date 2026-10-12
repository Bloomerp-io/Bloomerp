"""Signed carrier request fixtures for generated webhook scenarios."""

from django.http import HttpResponse
from twilio.request_validator import RequestValidator
from bloomerp.tests.base import RequestScenario
from bloomerp.tests.models.communication.voip.fixtures import VoIPFixtures
from bloomerp.models.communication.voip import PhoneCall
from bloomerp.models.communication.instant_messaging import IMMessage
from bloomerp.communication.builtins.voip.controller import callback_url


class WebhookFixtures(VoIPFixtures):
    """Build exact signature inputs for each real callback route."""

    kind: str

    def prepare_signed(self, scenario: RequestScenario) -> None:
        """Sign a carrier callback tied to the prepared account and line."""
        self.prepare_voip()
        scenario.view_kwargs = {"connection_id": self.connection.pk}
        scenario.data = {
            "AccountSid": self.connection.external_account_id,
            "From": self.identity.address,
            "To": self.number.number,
            "MessageSid": "SM" + "6" * 32,
            "Body": "Hello from the carrier",
            "CallSid": "CA" + "7" * 32,
            "CallStatus": "completed",
            "CallDuration": "12",
            "Direction": "inbound",
            "SequenceNumber": "1",
        }
        if self.kind == "message_status":
            self.message = IMMessage.objects.create(
                conversation=self.chat,
                sender=self.member,
                sequence=1,
                body="Outgoing",
                direction="outbound",
                client_id="send",
            )
            scenario.view_kwargs["message_id"] = self.message.pk
            scenario.data["MessageStatus"] = "delivered"
        scenario.headers = {
            "X-Twilio-Signature": RequestValidator("test-auth-token").compute_signature(
                callback_url(
                    self.connection,
                    self.kind,
                    **(
                        {"message_id": self.message.pk}
                        if self.kind == "message_status"
                        else {}
                    ),
                ),
                scenario.data,
            )
        }

    def prepare_unsigned(self, scenario: RequestScenario) -> None:
        """Remove the signature from an otherwise valid callback."""
        self.prepare_signed(scenario)
        scenario.headers = {}

    def prepare_replay(self, scenario: RequestScenario) -> None:
        """Deliver the same signed event once before the scenario's retry."""
        self.prepare_signed(scenario)
        response = self.client.post(
            self.get_endpoint(self.view_name, scenario.view_kwargs),
            scenario.data,
            headers=scenario.headers,
        )
        self.assertIn(response.status_code, (200, 204))

    def validate_persistence(self, response: HttpResponse) -> bool:
        """Assert that repeated callbacks leave a single record with normalized state."""
        if self.kind == "sms":
            return (
                IMMessage.objects.filter(
                    direction="inbound", body="Hello from the carrier"
                ).count()
                == 1
            )
        if self.kind == "call_status":
            call = PhoneCall.objects.get(provider_call_id="CA" + "7" * 32)
            return (
                call.status == "completed"
                and call.duration == 12
                and call.events.count() == 1
            )
        if self.kind == "message_status":
            self.message.refresh_from_db()
            return self.message.status == "delivered"
        return b"<Dial" in response.content and b"bloomerp_" in response.content
