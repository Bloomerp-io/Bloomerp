from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount


class EmailAttachmentMetadata(BaseModel):
    """Provider-backed reference to an inbound email attachment."""

    id: str
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0


class BloomerpEmail(BaseModel):
    """
    Lightweight provider-neutral email index data.

    """
    provider: str
    provider_message_id: str
    email_account_id: str
    mailbox: str = "INBOX"
    subject: str = ""
    sender: str = ""
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    date: datetime | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    is_read: bool = False
    flags: list[str] = Field(default_factory=list)
    snippet: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    attachments: list[EmailAttachmentMetadata] = Field(default_factory=list)

    def retrieval_metadata(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            include={
                "provider",
                "provider_message_id",
                "email_account_id",
                "mailbox",
                "message_id",
                "in_reply_to",
                "references",
                "date",
                "to",
                "cc",
                "flags",
                "raw",
                "attachments",
            },
            exclude_none=True,
        )


class EmailAttachment(BaseModel):
    """
    Provider-neutral attachment payload for outbound email.
    """
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class BaseEmailAdapter:
    """
    Base class for email synchronization adapters.
    """
    def __init__(self, email_account:"EmailAccount"):
        self.email_account = email_account
    
    
    def mark_as_read(self, email_id: str, *, mailbox: str = "INBOX"):
        """
        Mark an email as read in the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    def delete_email(self, email_id: str, *, mailbox: str = "INBOX"):
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
    ) -> str:
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


    def list_mailboxes(self) -> list[str]:
        """
        List available mailboxes/folders in the external service.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")
