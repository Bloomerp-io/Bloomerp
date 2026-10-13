import imaplib
import smtplib
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.providers.imap_smtp import (
    ACCOUNT_VALIDATION_TIMEOUT_SECONDS,
    SMTP_TIMEOUT_SECONDS,
    ImapSmtpAdapter,
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
