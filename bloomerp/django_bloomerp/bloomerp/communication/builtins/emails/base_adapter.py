from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount


class EmailAttachmentMetadata(BaseModel):
    """Provider-backed reference to an inbound email attachment."""

    id: str
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0


class CalendarEmailPart(BaseModel):
    """Decoded calendar MIME content, including its declared scheduling method."""

    content: str
    method: str = ""


class BloomerpEmail(BaseModel):
    """
    Lightweight provider-neutral email index data.

    """
    provider: str
    provider_message_id: str
    provider_message_id_scope: Literal["mailbox", "account"] = "mailbox"
    email_account_id: str
    mailbox: str = "INBOX"
    subject: str = ""
    sender: str = ""
    reply_to: list[str] = Field(default_factory=list)
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    date: datetime | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    is_read: bool = False
    is_draft: bool = False
    flags: list[str] = Field(default_factory=list)
    snippet: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    attachments: list[EmailAttachmentMetadata] = Field(default_factory=list)
    calendar_parts: list[CalendarEmailPart] = Field(default_factory=list)

    def retrieval_metadata(self) -> dict[str, Any]:
        """Serialize provider references needed to retrieve and reconcile this email."""
        return self.model_dump(
            mode="json",
            include={
                "provider",
                "provider_message_id",
                "provider_message_id_scope",
                "email_account_id",
                "mailbox",
                "message_id",
                "in_reply_to",
                "references",
                "reply_to",
                "is_draft",
                "date",
                "to",
                "cc",
                "flags",
                "raw",
                "attachments",
            },
            exclude_none=True,
        )


class EmailSyncBatch(BaseModel):
    """One durable mailbox page; cursors become valid only after local persistence."""

    messages: list[BloomerpEmail] = Field(default_factory=list)
    deleted_message_ids: list[str] = Field(default_factory=list)
    cursor: dict[str, Any] | None = None
    has_more: bool = False
    reset: bool = False


class EmailAttachment(BaseModel):
    """
    Provider-neutral attachment payload for outbound email.
    """
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
    calendar_method: str = ""


class EmailSendResult(BaseModel):
    """Correlate provider acceptance and message identity, without claiming recipient delivery."""

    provider_message_id: str
    message_id: str | None = None
    mailbox: str = "Sent"
    provider_message_id_scope: Literal["mailbox", "account"] = "account"


class EmailSendUnconfirmed(Exception):
    """Expose a provider reference when a send may have succeeded without confirmation."""

    def __init__(self, result: EmailSendResult) -> None:
        """Keep the pending message reference so callers can reconcile before retrying."""
        self.result = result
        super().__init__("Email send outcome is uncertain; synchronize Sent mail before retrying.")


class BaseEmailAdapter:
    """
    Base class for email synchronization adapters.
    """
    def __init__(self, email_account: "EmailAccount") -> None:
        """Bind provider operations to one configured email account."""
        self.email_account = email_account
    
    
    def validate_connection(self) -> list[str]:
        """Verify incoming and outgoing connections and return available mailboxes."""
        raise NotImplementedError("Subclasses must implement account connection validation.")

    def mark_as_read(self, email_id: str, *, mailbox: str = "INBOX") -> None:
        """
        Mark an email as read in the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    def delete_email(self, email_id: str, *, mailbox: str = "INBOX") -> None:
        """
        Delete an email from the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
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
    ) -> str | EmailSendResult:
        """
        Send an email using the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    
    def fetch_email_content(self, email_id: str, *, mailbox: str = "INBOX") -> str:
        """
        Fetch the content of an email from the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def fetch_email_attachment(
        self,
        email_id: str,
        attachment_id: str,
        *,
        mailbox: str = "INBOX",
    ) -> EmailAttachment | None:
        """Fetch one attachment by the reference returned in its metadata."""
        raise NotImplementedError("Subclasses must implement this method.")
    
    
    def search_emails(
        self,
        query: str | None = None,
        *,
        mailbox: str = "INBOX",
        limit: int = 50,
    ) -> list[BloomerpEmail]:
        """
        Search for emails in the external service based on a query.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    
    def sync_emails(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        *,
        mailbox: str = "INBOX",
    ) -> list[BloomerpEmail]:
        """
        Synchronize emails from the external service to the local system.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")


    def sync_batch(
        self,
        *,
        mailbox: str = "INBOX",
        cursor: dict[str, Any] | None = None,
        limit: int = 50,
        from_date: date | datetime | None = None,
        to_date: date | datetime | None = None,
    ) -> EmailSyncBatch:
        """Wrap legacy synchronization without changing its saved mailbox cursor."""
        return EmailSyncBatch(
            messages=self.sync_emails(
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                mailbox=mailbox,
            ),
        )

    def list_mailboxes(self) -> list[str]:
        """
        List available mailboxes/folders in the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
