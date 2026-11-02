"""Twilio call-history contracts using real SDK response objects."""

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase
from twilio.rest import Client
from twilio.rest.api.v2010.account.call import CallInstance

from bloomerp.communication.builtins.voip.builtins.twilio import TwilioAdapter
from bloomerp.communication.builtins.voip.definition import VoIPCallData, VoIPContext


class TestTwilioAdapter(SimpleTestCase):
    """Verify SDK response normalization without credentials or network access."""

    def test_sync_calls_uses_sdk_response_fields(self) -> None:
        """Import caller addresses and optional values from actual Twilio call objects."""
        account_sid = "AC" + "1" * 32
        client = Client(account_sid, "test-token")
        adapter = TwilioAdapter(VoIPContext("connection", account_sid, {}, {}))
        since = datetime(2026, 11, 1, tzinfo=timezone.utc)
        call_sid = "CA" + "2" * 32
        parent_sid = "CA" + "3" * 32
        for direction in ("inbound", "outbound-api"):
            with self.subTest(direction=direction):
                remote = CallInstance(
                    client.api.v2010,
                    {
                        "sid": call_sid,
                        "parent_call_sid": parent_sid,
                        "from": "+32470000001",
                        "to": "+32470000002",
                        "direction": direction,
                        "status": "completed",
                        "start_time": "Mon, 02 Nov 2026 09:00:00 +0000",
                        "end_time": "Mon, 02 Nov 2026 09:00:42 +0000",
                        "duration": "42",
                    },
                    account_sid,
                )
                empty = CallInstance(
                    client.api.v2010,
                    {"sid": "CA" + "4" * 32, "status": "queued"},
                    account_sid,
                )
                with patch.object(adapter, "client", return_value=client), patch.object(
                    client.calls, "stream", return_value=iter((remote, empty))
                ) as stream:
                    calls = adapter.sync_calls(since)
                stream.assert_called_once_with(start_time_after=since)
                self.assertEqual(
                    calls,
                    (
                        VoIPCallData(
                            call_sid,
                            parent_sid,
                            "+32470000001",
                            "+32470000002",
                            "inbound" if direction == "inbound" else "outbound",
                            "completed",
                            datetime(2026, 11, 2, 9, tzinfo=timezone.utc),
                            datetime(2026, 11, 2, 9, 0, 42, tzinfo=timezone.utc),
                            42,
                        ),
                        VoIPCallData(
                            "CA" + "4" * 32, "", "", "", "outbound", "queued", None, None, 0
                        ),
                    ),
                )
