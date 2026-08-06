
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.message import EmailMessage
from email.policy import default
from email.utils import formatdate, getaddresses, make_msgid, parsedate_to_datetime
from html import escape
import imaplib
import mimetypes
import re
import smtplib
import socket
from types import TracebackType
from typing import TYPE_CHECKING
from typing import Self

from django.core.exceptions import ValidationError

from bloomerp.communication.emails.base_adapter import BloomerpEmail
from bloomerp.communication.emails.base_adapter import BaseEmailAdapter
from bloomerp.communication.emails.base_adapter import EmailAttachment
from bloomerp.communication.emails.base_adapter import EmailAttachmentMetadata

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount


UID_PATTERN = re.compile(rb"\bUID\s+(\d+)\b")
FLAGS_PATTERN = re.compile(rb"\bFLAGS\s+\(([^)]*)\)")

class ImapSmtpAdapter(BaseEmailAdapter):
    def __init__(self, email_account: "EmailAccount"):
        super().__init__(email_account)
        self.connection: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self.connection is not None:
            return self.connection

        if not self.email_account.imap_host or not self.email_account.imap_port:
            raise ValidationError("IMAP host and port are required.")

        try:
            if self.email_account.imap_security == "ssl_tls":
                connection: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
                    self.email_account.imap_host,
                    self.email_account.imap_port,
                )
            else:
                connection = imaplib.IMAP4(
                    self.email_account.imap_host,
                    self.email_account.imap_port,
                )
                if self.email_account.imap_security == "starttls":
                    connection.starttls()

            connection.login(
                self.email_account.username or self.email_account.email_address,
                self.email_account.get_password_secret(),
            )
        except socket.gaierror as exc:
            raise ValidationError(
                f"Unable to resolve IMAP host '{self.email_account.imap_host}'. "
                "Use a hostname like 'imap.example.com' without a URL scheme."
            ) from exc
        except OSError as exc:
            raise ValidationError(
                f"Unable to connect to IMAP host '{self.email_account.imap_host}' "
                f"on port {self.email_account.imap_port}."
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise ValidationError(f"Unable to authenticate with the IMAP server: {exc}") from exc

        self.connection = connection
        return connection

    def close(self) -> None:
        if self.connection is None:
            return

        try:
            self.connection.close()
        except imaplib.IMAP4.error:
            pass
        finally:
            try:
                self.connection.logout()
            finally:
                self.connection = None

    def mark_as_read(self, email_id: str, *, mailbox: str = "INBOX"):
        connection = self.connect()
        self._select_mailbox(mailbox)
        connection.uid("STORE", email_id, "+FLAGS", r"(\Seen)")

    def delete_email(self, email_id: str, *, mailbox: str = "INBOX"):
        connection = self.connect()
        self._select_mailbox(mailbox)
        connection.uid("STORE", email_id, "+FLAGS", r"(\Deleted)")
        connection.expunge()

    def send_email(
        self,
        *,
        to: list[str],
        subject: str,
        body_html: str,
        body_text: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[EmailAttachment] | None = None,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> str:
        if not self.email_account.smtp_host or not self.email_account.smtp_port:
            raise ValidationError("SMTP host and port are required.")
        if not to:
            raise ValidationError("At least one recipient is required.")

        cc = cc or []
        bcc = bcc or []
        attachments = attachments or []
        message_id = make_msgid()

        message = EmailMessage()
        message["From"] = self.email_account.email_address
        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = message_id
        if reply_to:
            message["Reply-To"] = reply_to
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = " ".join(references)

        message.set_content(body_text or self._html_to_plain_text(body_html))
        if body_html:
            message.add_alternative(body_html, subtype="html")

        for attachment in attachments:
            content_type = attachment.content_type or mimetypes.guess_type(attachment.filename)[0] or "application/octet-stream"
            maintype, _, subtype = content_type.partition("/")
            message.add_attachment(
                attachment.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )

        recipients = [*to, *cc, *bcc]
        try:
            with self._connect_smtp() as smtp:
                smtp.send_message(message, from_addr=self.email_account.email_address, to_addrs=recipients)
        except socket.gaierror as exc:
            raise ValidationError(
                f"Unable to resolve SMTP host '{self.email_account.smtp_host}'. "
                "Use a hostname like 'smtp.example.com' without a URL scheme."
            ) from exc
        except OSError as exc:
            raise ValidationError(
                f"Unable to connect to SMTP host '{self.email_account.smtp_host}' "
                f"on port {self.email_account.smtp_port}."
            ) from exc
        except smtplib.SMTPException as exc:
            raise ValidationError(f"Unable to send email through the SMTP server: {exc}") from exc

        return message_id

    def fetch_email_content(self, email_id: str, *, mailbox: str = "INBOX") -> str:
        message = self._fetch_message(email_id, mailbox=mailbox)
        if message is None:
            return ""
        return self._extract_display_body(message)

    def fetch_email_attachment(
        self,
        email_id: str,
        attachment_id: str,
        *,
        mailbox: str = "INBOX",
    ) -> EmailAttachment | None:
        message = self._fetch_message(email_id, mailbox=mailbox)
        if message is None:
            return None

        for part_id, part in self._iter_leaf_parts(message):
            if part_id != attachment_id or not self._is_attachment(part):
                continue
            return EmailAttachment(
                filename=self._attachment_filename(part),
                content=part.get_payload(decode=True) or b"",
                content_type=part.get_content_type() or "application/octet-stream",
            )
        return None

    def _fetch_message(self, email_id: str, *, mailbox: str) -> Message | None:
        connection = self.connect()
        self._select_mailbox(mailbox, readonly=True)
        status, data = connection.uid("FETCH", email_id, "(BODY.PEEK[])")
        if status != "OK":
            return None

        for item in data:
            if isinstance(item, tuple) and isinstance(item[1], bytes):
                return message_from_bytes(item[1], policy=default)
        return None

    def search_emails(
        self,
        query: str | None = None,
        *,
        mailbox: str = "INBOX",
        limit: int = 50,
    ) -> list[BloomerpEmail]:
        connection = self.connect()
        self._select_mailbox(mailbox, readonly=True)

        uids = self._search_uids(query)
        limited_uids = list(reversed(uids))[:limit]
        emails: list[BloomerpEmail] = []

        for uid in limited_uids:
            email = self._fetch_email_index(uid, mailbox=mailbox)
            if email:
                emails.append(email)

        return emails

    def sync_emails(
        self,
        from_date: datetime | date | None = None,
        to_date: datetime | date | None = None,
        limit: int = 50,
        *,
        mailbox: str = "INBOX",
    ) -> list[BloomerpEmail]:
        connection = self.connect()
        self._select_mailbox(mailbox, readonly=True)

        uids = self._search_sync_uids(from_date=from_date, to_date=to_date)
        limited_uids = list(reversed(uids))[:limit]
        emails: list[BloomerpEmail] = []

        for uid in limited_uids:
            email = self._fetch_email_index(uid, mailbox=mailbox)
            if email:
                emails.append(email)

        return emails

    def list_mailboxes(self) -> list[str]:
        connection = self.connect()
        status, data = connection.list()
        if status != "OK" or not data:
            return []

        mailboxes: list[str] = []
        for item in data:
            if not isinstance(item, bytes):
                continue
            if not self._is_selectable_mailbox(item):
                continue
            mailbox = self._parse_mailbox_name(item)
            if mailbox:
                mailboxes.append(mailbox)
        return mailboxes

    def _select_mailbox(self, mailbox: str, readonly: bool = False) -> None:
        connection = self.connect()
        try:
            status, _ = connection.select(
                self._quote_mailbox(mailbox),
                readonly=readonly,
            )
        except imaplib.IMAP4.error as exc:
            raise ValidationError(
                f"Unable to select mailbox {mailbox}: {exc}"
            ) from exc
        if status != "OK":
            raise ValidationError(f"Unable to select mailbox {mailbox}.")

    def _search_uids(self, query: str | None) -> list[str]:
        connection = self.connect()
        search_query = (query or "").strip()
        if search_query:
            status, data = connection.uid(
                "SEARCH",
                "CHARSET",
                "UTF-8",
                "TEXT",
                self._quote_search_term(search_query),
            )
            if status != "OK":
                status, data = connection.uid("SEARCH", None, "ALL")
        else:
            status, data = connection.uid("SEARCH", None, "ALL")

        if status != "OK" or not data or not data[0]:
            return []
        return data[0].decode("ascii", errors="ignore").split()

    def _search_sync_uids(
        self,
        *,
        from_date: datetime | date | None = None,
        to_date: datetime | date | None = None,
    ) -> list[str]:
        connection = self.connect()
        criteria: list[str] = []
        if from_date:
            criteria.extend(["SINCE", self._format_imap_date(from_date)])
        if to_date:
            criteria.extend(["BEFORE", self._format_imap_date(self._next_day(to_date))])
        if not criteria:
            criteria.append("ALL")

        status, data = connection.uid("SEARCH", None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        return data[0].decode("ascii", errors="ignore").split()

    def _fetch_email_index(self, uid: str, *, mailbox: str) -> BloomerpEmail | None:
        connection = self.connect()
        status, data = connection.uid("FETCH", uid, "(UID FLAGS BODY.PEEK[])")
        if status != "OK":
            return None

        response_meta = b""
        message_bytes = b""
        for item in data:
            if not isinstance(item, tuple):
                continue
            if isinstance(item[0], bytes):
                response_meta += item[0]
            if isinstance(item[1], bytes):
                message_bytes += item[1]

        message = message_from_bytes(message_bytes, policy=default)
        flags = self._parse_flags(response_meta)
        provider_message_id = self._parse_uid(response_meta) or uid

        return BloomerpEmail(
            provider="imap",
            provider_message_id=provider_message_id,
            email_account_id=str(self.email_account.pk),
            mailbox=mailbox,
            subject=self._decode_header_value(message.get("subject", "")),
            sender=self._decode_header_value(message.get("from", "")),
            to=self._parse_address_header(message, "to"),
            cc=self._parse_address_header(message, "cc"),
            date=self._parse_date(message.get("date")),
            message_id=message.get("message-id"),
            in_reply_to=message.get("in-reply-to"),
            references=self._parse_message_ids(message.get("references", "")),
            is_read=self._has_seen_flag(flags),
            flags=flags,
            raw={
                "imap_uid": provider_message_id,
            },
            attachments=self._extract_attachment_metadata(message),
        )

    @staticmethod
    def _parse_message_ids(value: str) -> list[str]:
        """Return RFC message IDs from a References-style header."""
        return re.findall(r"<[^<>]+>", value or "")

    def _parse_uid(self, response_meta: bytes) -> str | None:
        match = UID_PATTERN.search(response_meta)
        if not match:
            return None
        return match.group(1).decode("ascii", errors="ignore")

    def _parse_flags(self, response_meta: bytes) -> list[str]:
        match = FLAGS_PATTERN.search(response_meta)
        if not match:
            return []
        return [
            flag.strip().strip('"')
            for flag in match.group(1).decode("utf-8", errors="ignore").split()
            if flag.strip()
        ]

    def _has_seen_flag(self, flags: list[str]) -> bool:
        return any(flag.lower() == r"\seen" for flag in flags)

    def _decode_header_value(self, value: str) -> str:
        if not value:
            return ""
        return str(make_header(decode_header(value)))

    def _parse_address_header(self, message: Message, header_name: str) -> list[str]:
        value = message.get(header_name)
        if not value:
            return []
        decoded_value = self._decode_header_value(value)
        return [address for _, address in getaddresses([decoded_value]) if address]

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

    def _format_imap_date(self, value: datetime | date) -> str:
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime("%d-%b-%Y")

    def _next_day(self, value: datetime | date) -> date:
        if isinstance(value, datetime):
            value = value.date()
        return value + timedelta(days=1)

    def _parse_mailbox_name(self, value: bytes) -> str:
        decoded_value = value.decode("utf-8", errors="ignore")
        quoted_match = re.search(r'"((?:\\.|[^"])*)"$', decoded_value)
        if quoted_match:
            return quoted_match.group(1).replace(r"\"", '"')

        parts = decoded_value.rsplit(" ", 1)
        return parts[-1].strip() if parts else ""

    def _is_selectable_mailbox(self, value: bytes) -> bool:
        decoded_value = value.decode("utf-8", errors="ignore").lstrip()
        flags_match = re.match(r"^\(([^)]*)\)", decoded_value)
        if not flags_match:
            return True

        flags = flags_match.group(1).split()
        return all(flag.casefold() != r"\noselect" for flag in flags)

    def _extract_display_body(self, message: Message) -> str:
        html_body = self._find_message_part(message, "text/html")
        if html_body:
            return html_body.strip()

        plain_body = self._find_message_part(message, "text/plain")
        if plain_body:
            escaped_body = escape(plain_body.strip())
            return (
                "<!doctype html>"
                "<html><body>"
                "<pre style=\"white-space: pre-wrap; font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\">"
                f"{escaped_body}"
                "</pre>"
                "</body></html>"
            )

        return ""

    def _extract_attachment_metadata(
        self,
        message: Message,
    ) -> list[EmailAttachmentMetadata]:
        attachments = []
        for part_id, part in self._iter_leaf_parts(message):
            if not self._is_attachment(part):
                continue
            attachments.append(
                EmailAttachmentMetadata(
                    id=part_id,
                    filename=self._attachment_filename(part),
                    content_type=part.get_content_type() or "application/octet-stream",
                    size=len(part.get_payload(decode=True) or b""),
                )
            )
        return attachments

    def _iter_leaf_parts(
        self,
        message: Message,
        prefix: str = "",
    ) -> Iterator[tuple[str, Message]]:
        if not message.is_multipart():
            yield prefix or "1", message
            return

        payload = message.get_payload()
        if not isinstance(payload, list):
            return
        for index, part in enumerate(payload, start=1):
            part_id = f"{prefix}.{index}" if prefix else str(index)
            yield from self._iter_leaf_parts(part, part_id)

    def _is_attachment(self, part: Message) -> bool:
        return part.get_content_disposition() == "attachment"

    def _attachment_filename(self, part: Message) -> str:
        filename = part.get_filename() or "attachment"
        return self._decode_header_value(str(filename))

    def _find_message_part(self, message: Message, content_type: str) -> str:
        if message.is_multipart():
            for part in message.walk():
                if part.is_multipart():
                    continue
                if part.get_content_disposition() == "attachment":
                    continue
                if part.get_content_type() == content_type:
                    return self._decode_part_payload(part)
            return ""

        if message.get_content_type() == content_type:
            return self._decode_part_payload(message)
        return ""

    def _decode_part_payload(self, part: Message) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            raw_payload = part.get_payload()
            return raw_payload if isinstance(raw_payload, str) else ""

        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    def _quote_search_term(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', r"\"")
        return f'"{escaped}"'

    def _quote_mailbox(self, mailbox: str) -> str:
        escaped = mailbox.replace("\\", "\\\\").replace('"', r"\"")
        return f'"{escaped}"'

    def _connect_smtp(self) -> smtplib.SMTP:
        if self.email_account.smtp_security == "ssl_tls":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                self.email_account.smtp_host,
                self.email_account.smtp_port,
            )
        else:
            smtp = smtplib.SMTP(
                self.email_account.smtp_host,
                self.email_account.smtp_port,
            )
            if self.email_account.smtp_security == "starttls":
                smtp.starttls()

        password = self.email_account.get_password_secret()
        username = self.email_account.username or self.email_account.email_address
        if username and password:
            smtp.login(username, password)
        return smtp

    def _html_to_plain_text(self, html: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+", " ", without_tags).strip()
