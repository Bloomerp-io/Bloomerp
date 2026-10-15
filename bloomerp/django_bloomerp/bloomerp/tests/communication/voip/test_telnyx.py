"""Pure carrier transport contracts with deterministic API responses."""

import json
from unittest.mock import patch
from uuid import uuid4

from django.core import signing
from django.test import SimpleTestCase

from bloomerp.communication.builtins.voip.builtins.telnyx import (
    TELNYX_PROVIDER,
    TelnyxAdapter,
)
from bloomerp.communication.builtins.voip.definition import VoIPContext


class TestTelnyxAdapter(SimpleTestCase):
    """Verify transport boundaries which do not require model or endpoint fixtures."""

    def setUp(self) -> None:
        """Bind a provider without any actual account credentials or network requests."""
        self.adapter = TelnyxAdapter(
            VoIPContext(
                "local",
                "account",
                {
                    "application_id": "123",
                    "credential_connection_id": "456",
                    "sip_subdomain": "test",
                },
                {"api_key": "secret"},
            )
        )

    def test_inventory_scoped_and_paginated(self) -> None:
        """Ignore another application and pending numbers even if the carrier filter leaks them."""
        pages = [
            {
                "data": [
                    {
                        "id": "one",
                        "phone_number": "+32470000001",
                        "connection_id": "123",
                        "status": "active",
                    }
                ],
                "meta": {"total_pages": 2},
            },
            {
                "data": [
                    {
                        "id": "other",
                        "phone_number": "+32470000002",
                        "connection_id": "999",
                        "status": "active",
                    },
                    {
                        "id": "pending",
                        "phone_number": "+32470000003",
                        "connection_id": "123",
                        "status": "pending",
                    },
                ],
                "meta": {"total_pages": 2},
            },
        ]
        with patch.object(self.adapter, "request", side_effect=pages) as request:
            numbers = self.adapter.list_numbers()
        self.assertEqual([item.external_id for item in numbers], ["one"])
        self.assertTrue(numbers[0].voice)
        self.assertFalse(numbers[0].sms)
        self.assertEqual(request.call_count, 2)
        self.assertIsNone(TELNYX_PROVIDER.number_purchase_schema)

    def test_reservation_reference_is_signed_and_scoped(self) -> None:
        """Bind the opaque browser reference to one instance connection and expiration."""
        call_id = uuid4()
        reference = self.adapter.browser_call_reference(call_id)
        self.assertEqual(self.adapter.resolve_call_reference(reference), call_id)
        with self.assertRaises(signing.BadSignature):
            self.adapter.resolve_call_reference(reference + "tampered")
        other = TelnyxAdapter(VoIPContext("other", "account", {}, {}))
        with self.assertRaises(signing.BadSignature):
            other.resolve_call_reference(reference)

    def test_reject_unrestricted_browser_profile(self) -> None:
        """Refuse credentials able to bypass server-selected telephone destinations."""
        with (
            patch.object(
                self.adapter,
                "request",
                return_value={
                    "data": {
                        "active": True,
                        "outbound": {"outbound_voice_profile_id": "paid-profile"},
                    }
                },
            ),
            self.assertRaises(ValueError),
        ):
            self.adapter.browser_connection()

    def test_token_contains_no_account_secrets(self) -> None:
        """Expose only a short-lived JWT and routing domain while bounding credential lifetime."""
        with (
            patch.object(self.adapter, "browser_connection"),
            patch.object(self.adapter, "credentials_for", return_value=[]),
            patch.object(
                self.adapter,
                "request",
                side_effect=[{"data": {"id": "credential"}}, "jwt-only"],
            ) as request,
        ):
            payload = json.loads(self.adapter.browser_token("actor"))
        self.assertEqual(
            payload, {"token": "jwt-only", "domain": "test.sip.telnyx.com"}
        )
        self.assertIn("expires_at", request.call_args_list[0].kwargs["data"])
        self.assertNotIn("secret", json.dumps(payload))
