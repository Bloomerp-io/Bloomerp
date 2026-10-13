"""Regression coverage for bounded outbound SMTP connections."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.providers.imap_smtp import (
    SMTP_TIMEOUT_SECONDS,
    ImapSmtpAdapter,
)


class SmtpTimeoutTests(SimpleTestCase):
    """Check that both SMTP modes bound network waits and report failures."""

    def test_ssl_connection_has_timeout(self) -> None:
        """Pass the timeout to SMTP_SSL on port 465."""
        account = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_security="ssl_tls",
            username="",
            email_address="sender@example.com",
            get_password_secret=Mock(return_value=""),
        )
        with patch("bloomerp.communication.builtins.emails.providers.imap_smtp.smtplib.SMTP_SSL") as smtp_class:
            ImapSmtpAdapter(account)._connect_smtp()

        smtp_class.assert_called_once_with("smtp.example.com", 465, timeout=SMTP_TIMEOUT_SECONDS)

    def test_starttls_connection_has_timeout(self) -> None:
        """Pass the timeout to SMTP and use it through STARTTLS."""
        account = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_security="starttls",
            username="",
            email_address="sender@example.com",
            get_password_secret=Mock(return_value=""),
        )
        with patch("bloomerp.communication.builtins.emails.providers.imap_smtp.smtplib.SMTP") as smtp_class:
            ImapSmtpAdapter(account)._connect_smtp()

        smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=SMTP_TIMEOUT_SECONDS)
        smtp_class.return_value.starttls.assert_called_once_with()

    def test_timed_out_send_is_reported_as_validation_error(self) -> None:
        """Use case: SMTP stalls. Expected result: Return an actionable validation error."""
        # 1. Configure the account stub with its current outgoing fields.
        account = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_security="ssl_tls",
            email_address="sender@example.com",
            smtp_envelope_sender="",
        )
        adapter = ImapSmtpAdapter(account)
        # 2. Simulate a timeout and verify the provider error is translated.
        with (
            patch.object(adapter, "_connect_smtp", side_effect=TimeoutError("timed out")),
            self.assertRaisesMessage(ValidationError, "SMTP server 'smtp.example.com' timed out"),
        ):
            adapter.send_email(to=["recipient@example.com"], subject="Hello", body_html="Hi")

    def test_failed_login_closes_smtp_socket(self) -> None:
        """Release the socket if authentication fails before the caller receives it."""
        account = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_security="ssl_tls",
            username="sender@example.com",
            email_address="sender@example.com",
            get_password_secret=Mock(return_value="bad password"),
        )
        with patch("bloomerp.communication.builtins.emails.providers.imap_smtp.smtplib.SMTP_SSL") as smtp_class:
            smtp_class.return_value.login.side_effect = TimeoutError("timed out")
            with self.assertRaises(TimeoutError):
                ImapSmtpAdapter(account)._connect_smtp()

        smtp_class.return_value.close.assert_called_once_with()
