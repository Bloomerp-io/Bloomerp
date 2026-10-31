import base64
import imaplib
import json
import smtplib
from datetime import timedelta
from email import message_from_bytes
from email.message import EmailMessage
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from bloomerp.communication.builtins.emails.base_adapter import (
    EmailAttachment,
    EmailSendUnconfirmed,
)
from bloomerp.communication.builtins.emails.providers.imap_smtp import (
    ACCOUNT_VALIDATION_TIMEOUT_SECONDS,
    SMTP_TIMEOUT_SECONDS,
    ImapSmtpAdapter,
)
from bloomerp.communication.builtins.emails.providers.outlook import (
    GRAPH_ROOT,
    OAUTH_SCOPES,
    GraphAuthorizationRequired,
    GraphRequestError,
    OutlookAdapter,
)
from bloomerp.models.communication.email_account import EmailAccount


class EmailConnectionValidationTests(SimpleTestCase):
    def setUp(self) -> None:
        """Prepare an unsaved account with fake incoming and outgoing servers."""
        self.account = EmailAccount(
            email_address="support@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            imap_host="imap.example.com",
            imap_port=993,
        )
        self.adapter = ImapSmtpAdapter(self.account)
        self.smtp = MagicMock()
        self.smtp.__enter__.return_value = self.smtp
        self.smtp.noop.return_value = (250, b"OK")
        self.smtp.mail.return_value = (250, b"OK")
        self.smtp.rset.return_value = (250, b"OK")
        self.imap = MagicMock()
        self.imap.list.return_value = ("OK", [b'() "/" "INBOX"', b'() "/" "Sent"'])
        self.smtp_patch = patch.object(
            self.adapter, "_connect_smtp", return_value=self.smtp
        )
        self.imap_patch = patch(
            "bloomerp.communication.builtins.emails.providers.imap_smtp.imaplib.IMAP4_SSL",
            return_value=self.imap,
        )
        self.smtp_connect = self.smtp_patch.start()
        self.imap_constructor = self.imap_patch.start()
        self.addCleanup(self.smtp_patch.stop)
        self.addCleanup(self.imap_patch.stop)

    def test_verifies_both_connections_without_sending_a_message(self) -> None:
        """Use case: Verify a new account. Expected result: SMTP and IMAP pass without sending."""
        # 1. Track validation across both fake servers.
        operations = MagicMock()
        operations.attach_mock(self.smtp.noop, "smtp_check")
        operations.attach_mock(self.imap.list, "imap_check")
        # 2. Validate outgoing mail before incoming mail and retrieve folder names.
        self.assertEqual(self.adapter.validate_connection(), ["INBOX", "Sent"])
        self.assertEqual(
            [call[0] for call in operations.mock_calls], ["smtp_check", "imap_check"]
        )
        self.imap_constructor.assert_called_once_with(
            "imap.example.com",
            993,
            timeout=ACCOUNT_VALIDATION_TIMEOUT_SECONDS,
        )
        # 3. Release both connections without creating or sending any message.
        self.smtp.__exit__.assert_called_once()
        self.imap.logout.assert_called_once()
        self.smtp.send_message.assert_not_called()
        self.imap.append.assert_not_called()

    def test_smtp_validation_uses_starttls_and_account_credentials(self) -> None:
        """Use case: Verify SMTP credentials. Expected result: Authenticate and probe without sending."""
        # 1. Exercise the real connection helper against a fake SMTP server.
        self.smtp_patch.stop()
        with (
            patch(
                "bloomerp.communication.builtins.emails.providers.imap_smtp.smtplib.SMTP",
                return_value=self.smtp,
            ) as smtp_constructor,
            patch.object(
                self.account, "get_password_secret", return_value="app-password"
            ),
        ):
            self.adapter.validate_smtp_connection()
        # 2. Check the shared connection path, credentials, and non-delivery probe.
        smtp_constructor.assert_called_once_with(
            "smtp.example.com", 587, timeout=SMTP_TIMEOUT_SECONDS
        )
        self.smtp.starttls.assert_called_once_with()
        self.smtp.login.assert_called_once_with("support@example.com", "app-password")
        self.smtp.noop.assert_called_once_with()
        self.smtp.mail.assert_called_once_with("support@example.com")
        self.smtp.rset.assert_called_once_with()
        self.smtp.send_message.assert_not_called()

    def test_alias_validation_checks_primary_envelope_without_delivery(self) -> None:
        """Validate the configured alias envelope without recipients or message submission."""
        self.account.smtp_envelope_sender = "primary@example.com"
        self.adapter.validate_connection()
        self.smtp.mail.assert_called_once_with("primary@example.com")
        self.smtp.rset.assert_called_once_with()
        self.smtp.rcpt.assert_not_called()
        self.smtp.data.assert_not_called()
        self.smtp.send_message.assert_not_called()

    def test_sender_rejection_is_actionable_redacted_and_skips_imap(self) -> None:
        """Reject unauthorized envelope senders and reset without exposing server text."""
        self.smtp.mail.return_value = (553, b"Sensitive provider diagnostic")
        with self.assertRaises(ValidationError) as raised:
            self.adapter.validate_connection()
        self.assertIn("support@example.com", str(raised.exception))
        self.assertIn("SMTP 553", str(raised.exception))
        self.assertIn("primary mailbox", str(raised.exception))
        self.assertNotIn("Sensitive provider diagnostic", str(raised.exception))
        self.smtp.rset.assert_called_once_with()
        self.smtp.__exit__.assert_called_once()
        self.imap_constructor.assert_not_called()
        self.smtp.send_message.assert_not_called()

    def test_sender_probe_exception_still_resets_connection(self) -> None:
        """Reset a failed sender probe and report a connection error without delivery."""
        self.smtp.mail.side_effect = smtplib.SMTPException("Sensitive diagnostic")
        with self.assertRaisesMessage(ValidationError, "SMTP connection check failed"):
            self.adapter.validate_connection()
        self.smtp.rset.assert_called_once_with()
        self.imap_constructor.assert_not_called()

    def test_failed_reset_prevents_successful_validation(self) -> None:
        """Do not accept validation when the sender probe cannot be reset."""
        self.smtp.rset.return_value = (421, b"Unavailable")
        with self.assertRaisesMessage(ValidationError, "SMTP connection reset failed"):
            self.adapter.validate_connection()
        self.imap_constructor.assert_not_called()

    def test_smtp_connection_errors_are_actionable_and_skip_imap(self) -> None:
        """Use case: SMTP rejects account setup. Expected result: Specific errors and no IMAP check."""
        # 1. Exercise credential, timeout, and network failures.
        failures = [
            (
                smtplib.SMTPAuthenticationError(535, b"Credentials rejected"),
                "SMTP authentication failed",
            ),
            (TimeoutError("timed out"), "SMTP server .* timed out"),
            (OSError("offline"), "Unable to connect to SMTP host"),
        ]
        for failure, expected in failures:
            with self.subTest(failure=failure):
                self.smtp_connect.side_effect = failure
                # 2. Stop before IMAP when the outgoing server fails validation.
                with self.assertRaisesRegex(ValidationError, expected):
                    self.adapter.validate_connection()
                self.imap_constructor.assert_not_called()
                self.smtp.send_message.assert_not_called()

    def test_rejected_smtp_probe_fails_validation_and_closes_connection(self) -> None:
        """Use case: SMTP NOOP is rejected. Expected result: Account validation fails cleanly."""
        # 1. Simulate a reachable outgoing server that rejects the probe.
        self.smtp.noop.return_value = (421, b"Service unavailable")
        # 2. Report a failed outgoing check and close without trying IMAP.
        with self.assertRaisesMessage(ValidationError, "SMTP connection check failed"):
            self.adapter.validate_connection()
        self.smtp.__exit__.assert_called_once()
        self.imap_constructor.assert_not_called()

    def test_imap_timeout_fails_validation_after_successful_smtp_probe(self) -> None:
        """Use case: IMAP stalls during setup. Expected result: Incoming validation fails."""
        # 1. Make incoming-server connection fail after SMTP verification.
        self.imap_constructor.side_effect = TimeoutError("timed out")
        # 2. Reject the account rather than treating SMTP alone as sufficient.
        with self.assertRaisesMessage(
            ValidationError, "Unable to connect to IMAP host"
        ):
            self.adapter.validate_connection()
        self.smtp.noop.assert_called_once()
        self.smtp.send_message.assert_not_called()

    def test_failed_imap_folder_discovery_fails_validation(self) -> None:
        """Use case: IMAP LIST fails. Expected result: Reject setup and release the connection."""
        # 1. A logged-in server reports that folder discovery failed.
        self.imap.list.return_value = ("NO", [b"Failed"])
        # 2. Do not silently accept the failure as an empty folder list.
        with self.assertRaisesMessage(ValidationError, "IMAP folder discovery failed"):
            self.adapter.validate_connection()
        self.imap.logout.assert_called_once()

    def test_failed_imap_login_releases_the_socket(self) -> None:
        """Use case: Incoming authentication fails. Expected result: Release the failed connection."""
        # 1. Reject login after the incoming socket has been constructed.
        self.imap.login.side_effect = imaplib.IMAP4.error("Credentials rejected")
        # 2. Close locally rather than leaking a socket from failed setup.
        with self.assertRaisesMessage(
            ValidationError, "Unable to authenticate with the IMAP server"
        ):
            self.adapter.validate_connection()
        self.imap.shutdown.assert_called_once_with()


class OutlookConnectionValidationTests(SimpleTestCase):
    """Exercise the Graph protocol contracts inside the existing adapter test module."""

    def setUp(self) -> None:
        """Configure an unsaved delegated mailbox with synthetic unexpired credentials."""
        self.account = EmailAccount(
            provider="outlook",
            email_address="support@example.com",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            oauth_tenant_id="11111111-2222-3333-4444-555555555555",
            access_token="access-token",
            refresh_token="refresh-token",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )
        self.adapter = OutlookAdapter(self.account)

    def response(self, data: dict[str, Any], *, status: int = 200) -> requests.Response:
        """Create a real HTTP response with predictable JSON and status semantics."""
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(data).encode()
        return response

    def test_authorization_uses_account_client_and_pkce(self) -> None:
        """Bind consent to user-supplied credentials, a tenant, state, and S256 PKCE."""
        url = self.adapter.get_authorization_url(
            redirect_uri="https://instance.example.com/oauth/callback/",
            state="one-use-state",
            code_verifier="a" * 64,
        )
        parts = urlsplit(url)
        parameters = parse_qs(parts.query)
        self.assertEqual(parts.netloc, "login.microsoftonline.com")
        self.assertIn(self.account.oauth_tenant_id, parts.path)
        self.assertEqual(parameters["client_id"], ["client-id"])
        self.assertEqual(parameters["state"], ["one-use-state"])
        self.assertEqual(parameters["code_challenge_method"], ["S256"])
        self.assertEqual(parameters["scope"], [OAUTH_SCOPES])
        self.assertNotIn("client-secret", url)
        self.account.oauth_tenant_id = "common"
        with self.assertRaises(ValidationError):
            self.adapter.get_authorization_url(
                redirect_uri="https://example.com",
                state="state",
                code_verifier="a" * 64,
            )

    def test_reconnect_rejects_another_verified_mailbox_identity(self) -> None:
        """Do not rebind an existing account when consent selected another user."""
        self.account.extra_settings = {
            "graph_user_id": "original-user",
            "graph_tenant_id": self.account.oauth_tenant_id,
        }
        with (
            patch.object(
                self.adapter,
                "_json_request",
                return_value={
                    "id": "another-user",
                    "mail": self.account.email_address,
                },
            ),
            self.assertRaisesMessage(ValidationError, "original Microsoft mailbox"),
        ):
            self.adapter._verify_identity()

    def test_authorization_exchanges_pkce_and_stores_verified_identity(self) -> None:
        """Encrypt delegated tokens after validating consent scopes and the Graph mailbox."""
        with (
            patch(
                "bloomerp.communication.utils.crypto._get_email_secret_key",
                return_value="test-key",
            ),
            patch(
                "bloomerp.communication.builtins.emails.providers.outlook.requests.post",
                return_value=self.response(
                    {
                        "access_token": "authorized-access",
                        "refresh_token": "authorized-refresh",
                        "expires_in": 3600,
                        "scope": "User.Read Mail.ReadWrite Mail.Send",
                    }
                ),
            ) as exchange,
            patch(
                "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
                return_value=self.response(
                    {
                        "id": "verified-user",
                        "mail": self.account.email_address,
                    }
                ),
            ),
        ):
            self.adapter.complete_authorization(
                code="one-use-code",
                redirect_uri="https://example.com/callback/",
                code_verifier="verifier",
            )
            self.assertEqual(
                self.account.get_access_token_secret(), "authorized-access"
            )
            self.assertEqual(
                self.account.get_refresh_token_secret(), "authorized-refresh"
            )
            self.assertNotEqual(self.account.access_token, "authorized-access")
        self.assertEqual(exchange.call_args.kwargs["data"]["code_verifier"], "verifier")
        self.assertEqual(
            exchange.call_args.kwargs["data"]["client_secret"], "client-secret"
        )
        self.assertEqual(self.account.extra_settings["graph_user_id"], "verified-user")
        self.assertEqual(
            self.account.extra_settings["graph_tenant_id"], self.account.oauth_tenant_id
        )
        self.assertTrue(self.account._state.adding)

    def test_content_attachment_and_remote_mutations_use_stable_ids(self) -> None:
        """Fetch plaintext safely, decode attachment bytes, and apply read/delete operations."""
        with patch(
            "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
            side_effect=[
                self.response({"body": {"contentType": "text", "content": "<script>"}}),
                self.response(
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": "note.txt",
                        "contentType": "text/plain",
                        "contentBytes": "bm90ZQ==",
                    }
                ),
                self.response({"isRead": True}),
                self.response({}, status=204),
            ],
        ) as request:
            self.assertEqual(
                self.adapter.fetch_email_content("stable/id"),
                "<pre>&lt;script&gt;</pre>",
            )
            attachment = self.adapter.fetch_email_attachment(
                "stable/id", "attachment/id"
            )
            self.assertEqual(attachment.content, b"note")
            self.adapter.mark_as_read("stable/id")
            self.adapter.delete_email("stable/id")
        self.assertEqual(
            request.call_args_list[1].args[1],
            f"{GRAPH_ROOT}/me/messages/stable%2Fid/attachments/attachment%2Fid",
        )
        self.assertEqual(request.call_args_list[2].kwargs["json"], {"isRead": True})
        self.assertEqual(request.call_args_list[3].args[0], "DELETE")

    def test_send_preserves_mime_headers_and_immutable_id(self) -> None:
        """Preserve reply metadata, hidden recipients, and attachments through one draft send."""
        with patch(
            "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
            side_effect=[
                self.response({"id": "immutable-id"}, status=201),
                self.response({}, status=202),
            ],
        ) as request:
            result = self.adapter.send_email(
                to=["to@example.com"],
                cc=["cc@example.com"],
                bcc=["hidden@example.com"],
                subject="Reply",
                body_html='<p>Hello</p><img src="cid:logo@example.com">',
                in_reply_to="<original@example.com>",
                references=["<original@example.com>"],
                reply_to="reply@example.com",
                attachments=[
                    EmailAttachment(
                        filename="note.txt", content=b"note", content_type="text/plain"
                    ),
                    EmailAttachment(filename="logo.png", content=b"image-bytes", content_type="image/png", disposition="inline", content_id="logo@example.com"),
                ],
            )
        self.assertEqual(result.provider_message_id, "immutable-id")
        self.assertTrue(result.message_id.startswith("<"))
        self.assertEqual(request.call_count, 2)
        created = request.call_args_list[0]
        mime = message_from_bytes(base64.b64decode(created.kwargs["data"]))
        self.assertEqual(mime["Bcc"], "hidden@example.com")
        self.assertEqual(mime["In-Reply-To"], "<original@example.com>")
        self.assertEqual(mime["References"], "<original@example.com>")
        self.assertEqual(mime["Reply-To"], "reply@example.com")
        self.assertEqual(
            [part.get_filename() for part in mime.walk() if part.get_filename()],
            ["logo.png", "note.txt"],
        )
        inline = next(part for part in mime.walk() if part.get_content_disposition() == "inline")
        self.assertEqual(inline["Content-ID"], "<logo@example.com>")
        self.assertEqual(inline.get_payload(decode=True), b"image-bytes")
        related = next(part for part in mime.walk() if part.get_content_type() == "multipart/related")
        self.assertEqual(related.get_payload()[0].get_content_type(), "text/html")
        self.assertIn(b'cid:logo@example.com', related.get_payload()[0].get_payload(decode=True))
        self.assertEqual(created.kwargs["headers"]["Prefer"], 'IdType="ImmutableId"')
        self.assertEqual(
            request.call_args_list[1].args,
            ("POST", f"{GRAPH_ROOT}/me/messages/immutable-id/send"),
        )

    def test_send_timeout_is_not_retried_and_preserves_reconciliation_id(self) -> None:
        """An ambiguous send exposes the draft identity and never submits it twice."""
        with (
            patch(
                "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
                side_effect=[
                    self.response({"id": "draft-id"}, status=201),
                    requests.Timeout("secret diagnostic"),
                ],
            ) as request,
            self.assertRaises(EmailSendUnconfirmed) as raised,
        ):
            self.adapter.send_email(
                to=["to@example.com"], subject="Hello", body_html="Hi"
            )
        self.assertEqual(request.call_count, 2)
        self.assertEqual(raised.exception.result.provider_message_id, "draft-id")
        self.assertTrue(raised.exception.result.message_id.startswith("<"))
        self.assertNotIn("secret diagnostic", str(raised.exception))

    def test_folder_ids_preserve_localized_labels_and_well_known_roles(self) -> None:
        """Identify Inbox and Sent independently of localized folder display names."""
        configured = {
            "sent-id": {
                "label": "Custom sent",
                "main_folder": True,
                "sent_folder": False,
                "color": "",
            }
        }
        self.account.mailboxes = configured
        with (
            patch.object(
                self.adapter,
                "_json_request",
                side_effect=[{"id": "inbox-id"}, {"id": "sent-id"}],
            ),
            patch.object(
                self.adapter,
                "_collection",
                return_value=[
                    {"id": "inbox-id", "displayName": "Postvak IN"},
                    {"id": "sent-id", "displayName": "Verzonden items"},
                ],
            ),
        ):
            self.assertEqual(self.adapter.list_mailboxes(), ["inbox-id", "sent-id"])
        defaults = self.adapter.mailbox_defaults()
        self.assertEqual(defaults["inbox-id"]["label"], "Postvak IN")
        self.assertTrue(defaults["inbox-id"]["main_folder"])
        self.assertTrue(defaults["sent-id"]["sent_folder"])
        self.assertEqual(self.account.mailboxes, configured)

    def test_delta_page_preserves_cursor_tombstone_and_read_state(self) -> None:
        """A resumable page carries immutable IDs, read state, and folder removals."""
        link = f"{GRAPH_ROOT}/me/mailFolders/folder/messages/delta?$skiptoken=next"
        with patch.object(
            self.adapter,
            "_json_request",
            side_effect=[
                {
                    "value": [
                        {"id": "removed-id", "@removed": {"reason": "deleted"}},
                        {
                            "id": "message-id",
                            "subject": "Hello",
                            "from": {"emailAddress": {"address": "sender@example.com"}},
                            "isRead": True,
                        },
                    ],
                    "@odata.nextLink": link,
                },
                GraphRequestError("Missing", status_code=404),
            ],
        ):
            batch = self.adapter.sync_batch(mailbox="folder")
        self.assertTrue(batch.reset)
        self.assertTrue(batch.has_more)
        self.assertEqual(batch.cursor, {"next_link": link})
        self.assertEqual(batch.deleted_message_ids, ["removed-id"])
        self.assertEqual(batch.messages[0].provider_message_id_scope, "account")
        self.assertTrue(batch.messages[0].is_read)

    def test_tombstones_resolve_moves_before_deleting_local_identity(self) -> None:
        """Distinguish a move to an already-polled folder from a confirmed remote deletion."""
        with patch.object(
            self.adapter,
            "_json_request",
            side_effect=[
                {
                    "value": [
                        {"id": "moved-id", "@removed": {"reason": "deleted"}},
                        {"id": "deleted-id", "@removed": {"reason": "deleted"}},
                    ],
                    "@odata.deltaLink": f"{GRAPH_ROOT}/me/mailFolders/source/messages/delta?$deltatoken=new",
                },
                {
                    "id": "moved-id",
                    "subject": "Keep local metadata",
                    "parentFolderId": "already-polled-folder",
                    "isRead": True,
                },
                GraphRequestError("Missing", status_code=404),
            ],
        ) as request:
            batch = self.adapter.sync_batch(
                mailbox="source", cursor={"delta_link": f"{GRAPH_ROOT}/old"}
            )
        self.assertEqual(request.call_count, 3)
        self.assertEqual(batch.deleted_message_ids, ["moved-id", "deleted-id"])
        self.assertEqual(len(batch.messages), 1)
        self.assertEqual(batch.messages[0].provider_message_id, "moved-id")
        self.assertEqual(batch.messages[0].mailbox, "already-polled-folder")

    def test_calendar_candidates_reuse_incoming_mime_extraction(self) -> None:
        """Extract scheduling MIME for Graph meeting messages and calendar attachments only."""
        for kind, method in (
            ("event", "REQUEST"),
            ("event", "REPLY"),
            ("attachment", "CANCEL"),
        ):
            mime = EmailMessage()
            mime.set_content("Meeting notification")
            mime.add_alternative(
                f"BEGIN:VCALENDAR\r\nMETHOD:{method}\r\nEND:VCALENDAR\r\n",
                subtype="calendar",
                params={"method": method},
            )
            response = requests.Response()
            response.status_code = 200
            response._content = mime.as_bytes()
            message = {"id": "meeting-id", "hasAttachments": kind == "attachment"}
            if kind == "event":
                message["@odata.type"] = "#microsoft.graph.eventMessageRequest"
            with (
                self.subTest(kind=kind, method=method),
                patch.object(
                    self.adapter,
                    "_collection",
                    return_value=[
                        {
                            "id": "calendar-id",
                            "name": "invite.ics",
                            "contentType": "text/calendar",
                        }
                    ],
                ),
                patch(
                    "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
                    return_value=response,
                ) as request,
            ):
                email = self.adapter._email(message, mailbox="inbox-id")
                self.assertEqual(email.calendar_parts[0].method, method)
                self.assertIn(f"METHOD:{method}", email.calendar_parts[0].content)
                self.assertEqual(
                    request.call_args.args[1],
                    f"{GRAPH_ROOT}/me/messages/meeting-id/$value",
                )
                self.assertEqual(
                    self.adapter._email(
                        {"id": "ordinary-id"}, mailbox="inbox-id"
                    ).calendar_parts,
                    [],
                )
                self.assertEqual(request.call_count, 1)

    def test_expired_cursor_restarts_a_complete_snapshot(self) -> None:
        """Request stale-local-record reconciliation when Graph expires its delta token."""
        for status in (410, 404):
            with (
                self.subTest(status=status),
                patch(
                    "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
                    side_effect=[
                        self.response(
                            {"error": {"code": "syncStateNotFound"}}, status=status
                        ),
                        self.response(
                            {
                                "value": [],
                                "@odata.deltaLink": f"{GRAPH_ROOT}/me/mailFolders/folder/messages/delta?$deltatoken=new",
                            }
                        ),
                    ],
                ) as request,
            ):
                batch = self.adapter.sync_batch(
                    mailbox="folder", cursor={"delta_link": f"{GRAPH_ROOT}/old"}
                )
            self.assertEqual(request.call_count, 2)
            self.assertTrue(batch.reset)
            self.assertFalse(batch.has_more)

    def test_throttle_backoff_and_untrusted_continuations(self) -> None:
        """Honor bounded Retry-After and reject token-bearing requests to foreign origins."""
        throttled = self.response(
            {"error": {"message": "secret diagnostic"}}, status=429
        )
        throttled.headers["Retry-After"] = "2"
        with (
            patch(
                "bloomerp.communication.builtins.emails.providers.outlook.requests.request",
                side_effect=[throttled, self.response({"id": "ok"})],
            ) as request,
            patch(
                "bloomerp.communication.builtins.emails.providers.outlook.time.sleep"
            ) as sleep,
        ):
            self.assertEqual(self.adapter._json_request("GET", "/me"), {"id": "ok"})
            sleep.assert_called_once_with(2.0)
            with self.assertRaises(GraphRequestError):
                self.adapter._json_request(
                    "GET", "https://attacker.example.com/v1.0/me"
                )
        self.assertEqual(request.call_count, 2)


class OutlookTokenRefreshTests(TransactionTestCase):
    """Check token rotation and stale-worker behavior against persisted account secrets."""

    def test_refresh_persists_rotation_and_reuses_another_workers_token(self) -> None:
        """Refresh once under a row lock and keep stale workers from reusing rotated secrets."""
        with patch(
            "bloomerp.communication.utils.crypto._get_email_secret_key",
            return_value="test-key",
        ):
            account = EmailAccount.objects.create(
                provider="outlook",
                status=EmailAccount.Status.ACTIVE,
                email_address="refresh@example.com",
                oauth_client_id="client",
                oauth_client_secret="secret",
                oauth_tenant_id="11111111-2222-3333-4444-555555555555",
                access_token="expired",
                refresh_token="old-refresh",
                token_expires_at=timezone.now() - timedelta(minutes=1),
            )
            account.extra_settings = {
                "graph_configuration_digest": OutlookAdapter(
                    account
                )._grant_fingerprint()
            }
            account.save(update_fields=["extra_settings"])
            stale_account = EmailAccount.objects.get(pk=account.pk)
            with patch.object(
                OutlookAdapter,
                "_token_request",
                return_value={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            ) as exchange:
                OutlookAdapter(account).prepare_authorization()
                self.assertEqual(account.get_access_token_secret(), "new-access")
                OutlookAdapter(stale_account).prepare_authorization()
                self.assertEqual(
                    OutlookAdapter(stale_account)._access_token(), "new-access"
                )
            exchange.assert_called_once_with(
                {"grant_type": "refresh_token", "refresh_token": "old-refresh"}
            )
            account.refresh_from_db()
            self.assertEqual(account.get_refresh_token_secret(), "new-refresh")
            self.assertNotEqual(account.refresh_token, "new-refresh")
            # A cached valid token cannot survive a persisted disconnection.
            EmailAccount.objects.filter(pk=account.pk).update(
                status=EmailAccount.Status.DRAFT, access_token="", refresh_token=""
            )
            with self.assertRaises(GraphAuthorizationRequired):
                OutlookAdapter(stale_account)._access_token()

    def test_caller_transaction_cannot_roll_back_rotated_provider_credentials(self) -> None:
        """Refuse token rotation before provider I/O when the caller can roll back its storage."""
        with patch(
            "bloomerp.communication.utils.crypto._get_email_secret_key",
            return_value="test-key",
        ):
            account = EmailAccount.objects.create(
                provider="outlook",
                status=EmailAccount.Status.ACTIVE,
                email_address="transaction@example.com",
                oauth_client_id="client",
                oauth_client_secret="secret",
                oauth_tenant_id="11111111-2222-3333-4444-555555555555",
                access_token="current-access",
                refresh_token="current-refresh",
                token_expires_at=timezone.now() + timedelta(hours=1),
            )
            adapter = OutlookAdapter(account)
            account.extra_settings = {"graph_configuration_digest": adapter._grant_fingerprint()}
            account.save(update_fields=["extra_settings"])
            with patch.object(OutlookAdapter, "_token_request") as exchange:
                with transaction.atomic():
                    self.assertEqual(adapter._access_token(), "current-access")
                    with self.assertRaisesMessage(GraphRequestError, "needs preparation"):
                        adapter._access_token(rejected_token="current-access")
                account.token_expires_at = timezone.now() - timedelta(minutes=1)
                account.save(update_fields=["token_expires_at"])
                with transaction.atomic(), self.assertRaisesMessage(GraphRequestError, "needs preparation"):
                    adapter._access_token()
                exchange.assert_not_called()
            account.refresh_from_db()
            self.assertEqual(account.get_access_token_secret(), "current-access")
            self.assertEqual(account.get_refresh_token_secret(), "current-refresh")
            self.assertEqual(account.status, EmailAccount.Status.ACTIVE)

    def test_revoked_refresh_disables_polling_after_transaction_rollback(self) -> None:
        """Persist a redacted reconnect state when refresh credentials were revoked."""
        with patch(
            "bloomerp.communication.utils.crypto._get_email_secret_key",
            return_value="test-key",
        ):
            account = EmailAccount.objects.create(
                provider="outlook",
                status=EmailAccount.Status.ACTIVE,
                email_address="revoked@example.com",
                oauth_client_id="client",
                oauth_client_secret="secret",
                oauth_tenant_id="11111111-2222-3333-4444-555555555555",
                access_token="expired",
                refresh_token="revoked-refresh",
                token_expires_at=timezone.now() - timedelta(minutes=1),
            )
            account.extra_settings = {
                "graph_configuration_digest": OutlookAdapter(
                    account
                )._grant_fingerprint()
            }
            account.save(update_fields=["extra_settings"])
            with (
                patch.object(
                    OutlookAdapter,
                    "_token_request",
                    side_effect=GraphAuthorizationRequired("Reconnect"),
                ),
                self.assertRaises(GraphAuthorizationRequired),
            ):
                OutlookAdapter(account)._access_token()
            account.refresh_from_db()
            self.assertEqual(account.status, EmailAccount.Status.ERROR)
            self.assertFalse(account.sync_enabled)
            self.assertIn("Reconnect", account.validation_error)
            self.assertNotIn("revoked-refresh", account.validation_error)

    def test_new_adapter_rejects_a_grant_after_credential_rotation(self) -> None:
        """Require new consent when persisted client credentials no longer match the grant."""
        with patch(
            "bloomerp.communication.utils.crypto._get_email_secret_key",
            return_value="test-key",
        ):
            account = EmailAccount.objects.create(
                provider="outlook",
                status=EmailAccount.Status.ACTIVE,
                email_address="rotated@example.com",
                oauth_client_id="original-client",
                oauth_client_secret="secret",
                oauth_tenant_id="11111111-2222-3333-4444-555555555555",
                access_token="unexpired",
                refresh_token="refresh",
                token_expires_at=timezone.now() + timedelta(hours=1),
            )
            account.extra_settings = {
                "graph_configuration_digest": OutlookAdapter(
                    account
                )._grant_fingerprint()
            }
            account.oauth_client_id = "replacement-client"
            account.save(update_fields=["extra_settings", "oauth_client_id"])
            with self.assertRaisesMessage(
                GraphAuthorizationRequired, "credentials changed"
            ):
                OutlookAdapter(EmailAccount.objects.get(pk=account.pk))._access_token()
            account.refresh_from_db()
            self.assertEqual(account.status, EmailAccount.Status.ERROR)
            self.assertFalse(account.sync_enabled)
