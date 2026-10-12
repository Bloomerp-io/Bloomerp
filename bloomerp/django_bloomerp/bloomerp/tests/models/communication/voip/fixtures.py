"""Shared carrier fixtures for generated model and endpoint scenarios."""

from typing import Any
from django.test import override_settings
from django.utils import timezone
from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
    IMIdentity,
)


class VoIPFixtures:
    """Create two isolated carrier accounts and one assigned phone conversation."""

    def prepare_voip(self) -> None:
        """Prepare encrypted carrier credentials and explicit staff line assignments."""
        from django.contrib.auth import get_user_model

        if (
            not hasattr(self, "admin_user")
            or not get_user_model().objects.filter(pk=self.admin_user.pk).exists()
        ):
            self.admin_user = get_user_model().objects.create(
                username="voip_admin", is_staff=True, is_superuser=True
            )
            self.normal_user = get_user_model().objects.create(
                username="voip_staff", is_staff=True
            )
        self.enterContext(
            override_settings(
                BLOOMERP_CONFIG=BloomerpConfig(email_secret_key="voip-test-key")
            )
        )
        self.connection = VoIPConnection(
            name="Carrier",
            provider="twilio",
            external_account_id="AC" + "1" * 32,
            status="active",
            settings={
                "public_url": "https://example.test",
                "browser_calling": True,
                "api_key_sid": "SK" + "2" * 32,
                "application_sid": "AP" + "3" * 32,
            },
            created_by=self.admin_user,
        )
        self.connection.set_credentials(
            {"auth_token": "test-auth-token", "api_key_secret": "test-api-secret"}
        )
        self.connection.save()
        self.other_connection = VoIPConnection.objects.create(
            name="Other carrier", provider="twilio", external_account_id="AC" + "4" * 32
        )
        self.number = VoIPNumber.objects.create(
            connection=self.connection,
            number="+32470000001",
            provider_number_id="PN" + "1" * 32,
            supports_sms=True,
            supports_voice=True,
        )
        self.number.assigned_users.add(self.normal_user)
        self.identity = IMIdentity.objects.create(
            provider_key="phone", external_id="+32470000002", address="+32470000002"
        )
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

    def call_args(self) -> dict[str, Any]:
        """Return a valid retained outgoing call for the prepared phone conversation."""
        return {
            "connection": self.connection,
            "number": self.number,
            "conversation": self.chat,
            "direction": "outbound",
            "from_address": self.number.number,
            "to_address": self.identity.address,
            "provider_call_id": "CA" + "5" * 32,
            "started_at": timezone.now(),
        }
