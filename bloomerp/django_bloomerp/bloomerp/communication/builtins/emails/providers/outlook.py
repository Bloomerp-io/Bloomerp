"""Microsoft Graph mail adapter using account-owned delegated OAuth credentials."""

import base64
import hashlib
import json
import re
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, make_msgid, parsedate_to_datetime
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

import requests
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import strip_tags

from bloomerp.communication.builtins.emails.base_adapter import (
    BaseEmailAdapter,
    BloomerpEmail,
    CalendarEmailPart,
    EmailAttachment,
    EmailAttachmentMetadata,
    EmailSendResult,
    EmailSendUnconfirmed,
    EmailSyncBatch,
)

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
OAUTH_SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send"
REQUEST_TIMEOUT = (5, 30)
MAX_RETRY_WAIT = 30
MESSAGE_FIELDS = (
    "id,subject,from,toRecipients,ccRecipients,replyTo,receivedDateTime,"
    "sentDateTime,internetMessageId,internetMessageHeaders,isRead,bodyPreview,"
    "hasAttachments,parentFolderId,isDraft"
)


class GraphRequestError(ValidationError):
    """Expose a safe provider error while preserving its HTTP status for recovery."""

    def __init__(
        self, message: str, *, status_code: int = 0, cursor_expired: bool = False
    ) -> None:
        """Keep server diagnostics out of validation messages and logs."""
        super().__init__(message)
        self.status_code = status_code
        self.cursor_expired = cursor_expired


class GraphAuthorizationRequired(GraphRequestError):
    """Indicate that consent or credentials must be repaired before polling again."""


class OutlookAdapter(BaseEmailAdapter):
    """Read and send a delegated mailbox through Microsoft Graph v1.0."""

    def __init__(self, email_account: "EmailAccount") -> None:
        """Bind one account and keep discovered folder defaults separate from user settings."""
        super().__init__(email_account)
        self._mailbox_defaults: dict[str, dict[str, Any]] = {}

    def _authority(self) -> str:
        """Build a fixed-host authorization authority from the account tenant."""
        try:
            tenant = str(UUID(self.email_account.oauth_tenant_id.strip()))
        except ValueError as exc:
            raise ValidationError(
                "Enter the Microsoft directory tenant ID as a UUID."
            ) from exc
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    def get_authorization_url(
        self, *, redirect_uri: str, state: str, code_verifier: str
    ) -> str:
        """Start delegated consent with S256 PKCE and session-bound OAuth state."""
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        parameters = {
            "client_id": self.email_account.oauth_client_id,
            "response_type": "code",
            "response_mode": "query",
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
            "login_hint": self.email_account.email_address,
        }
        return f"{self._authority()}/authorize?{urlencode(parameters)}"

    def complete_authorization(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> None:
        """Exchange a code and bind tokens to a mailbox verified through Graph."""
        tokens = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        self._apply_tokens(self.email_account, tokens)
        if not tokens.get("refresh_token"):
            raise ValidationError(
                "Microsoft did not grant offline access. Reconnect the account."
            )
        self._verify_identity()
        self.email_account.oauth_scopes = OAUTH_SCOPES
        self.email_account.extra_settings["authorization_revision"] = secrets.token_hex(
            16
        )
        self.email_account.extra_settings["graph_configuration_digest"] = (
            self._grant_fingerprint()
        )

    def _grant_fingerprint(self) -> str:
        """Bind a verified grant to credentials without storing another copy of its secret."""
        account = self.email_account
        values = [
            account.provider,
            account.email_address.casefold(),
            account.oauth_client_id,
            str(UUID(account.oauth_tenant_id.strip())),
            account.get_oauth_client_secret(),
            account.extra_settings.get("graph_user_id"),
        ]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def _verify_identity(self) -> None:
        """Verify the selected mailbox and reject reconnects to another identity."""
        profile = self._json_request(
            "GET", "/me", params={"$select": "id,mail,userPrincipalName"}
        )
        identity = str(profile.get("id") or "")
        addresses = {
            str(profile.get(field) or "").casefold()
            for field in ("mail", "userPrincipalName")
        }
        if not identity or self.email_account.email_address.casefold() not in addresses:
            raise ValidationError(
                "Sign in with the Microsoft mailbox entered for this email account."
            )
        settings = dict(self.email_account.extra_settings or {})
        previous = settings.get("graph_user_id")
        tenant = str(UUID(self.email_account.oauth_tenant_id.strip()))
        if previous and (
            previous != identity or settings.get("graph_tenant_id") != tenant
        ):
            raise ValidationError(
                "Reconnect using the original Microsoft mailbox and tenant."
            )
        settings.update(graph_user_id=identity, graph_tenant_id=tenant)
        self.email_account.extra_settings = settings

    def _token_request(self, grant: dict[str, str]) -> dict[str, Any]:
        """Exchange credentials once without retrying rotating token operations."""
        try:
            response = requests.post(
                f"{self._authority()}/token",
                data={
                    "client_id": self.email_account.oauth_client_id,
                    "client_secret": self.email_account.get_oauth_client_secret(),
                    "scope": OAUTH_SCOPES,
                    **grant,
                },
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise GraphRequestError(
                "Microsoft authorization is temporarily unavailable. Try again."
            ) from exc
        if response.status_code != 200:
            error_class = (
                GraphAuthorizationRequired
                if response.status_code in {400, 401, 403}
                else GraphRequestError
            )
            raise error_class(
                "Microsoft authorization failed. Check the client credentials and reconnect the account.",
                status_code=response.status_code,
            )
        try:
            tokens = response.json()
        except ValueError as exc:
            raise GraphRequestError(
                "Microsoft returned an invalid authorization response."
            ) from exc
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            raise GraphRequestError("Microsoft did not return an access token.")
        granted = {
            scope.rsplit("/", 1)[-1].casefold()
            for scope in str(tokens.get("scope", "")).split()
        }
        if not {"user.read", "mail.readwrite", "mail.send"}.issubset(granted):
            raise GraphAuthorizationRequired(
                "Grant mailbox read/write, send, and profile access before connecting."
            )
        return tokens

    def _apply_tokens(self, account: "EmailAccount", tokens: dict[str, Any]) -> None:
        """Encrypt replacement tokens and compute expiry without persisting other fields."""
        try:
            expires_in = max(0, int(tokens["expires_in"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphRequestError(
                "Microsoft returned an invalid token expiry."
            ) from exc
        account.set_access_token_secret(str(tokens["access_token"]))
        if tokens.get("refresh_token"):
            account.set_refresh_token_secret(str(tokens["refresh_token"]))
        account.token_expires_at = timezone.now() + timedelta(seconds=expires_in)

    def prepare_authorization(self) -> None:
        """Persist a fresh grant before a caller starts a transaction that might roll back."""
        self._access_token(rejected_token=self.email_account.get_access_token_secret())

    def _access_token(self, *, rejected_token: str | None = None) -> str:
        """Check current authorization and serialize refreshes of rotating tokens."""
        account = self.email_account
        if account._state.adding:
            token = account.get_access_token_secret()
            if (
                token
                and account.token_expires_at
                and account.token_expires_at > timezone.now()
            ):
                return token
            raise GraphRequestError(
                "Connect the Microsoft account before accessing its mailbox."
            )
        caller_in_transaction = transaction.get_connection().in_atomic_block
        try:
            with transaction.atomic():
                locked = type(account).objects.select_for_update().get(pk=account.pk)
                self._check_authorization_binding(locked)
                account.access_token = locked.access_token
                account.refresh_token = locked.refresh_token
                account.token_expires_at = locked.token_expires_at
                token = locked.get_access_token_secret()
                if not (
                    token
                    and token != rejected_token
                    and locked.token_expires_at
                    and locked.token_expires_at > timezone.now() + timedelta(seconds=60)
                ):
                    if caller_in_transaction:
                        raise GraphRequestError(
                            "Mailbox authorization needs preparation before this operation. Try again."
                        )
                    refresh_token = locked.get_refresh_token_secret()
                    if not refresh_token:
                        raise GraphAuthorizationRequired(
                            "Reconnect the Microsoft account to restore mailbox access."
                        )
                    refreshed = OutlookAdapter(locked)
                    tokens = refreshed._token_request(
                        {
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                        }
                    )
                    self._apply_tokens(locked, tokens)
                    locked.save(
                        update_fields=[
                            "access_token",
                            "refresh_token",
                            "token_expires_at",
                            "datetime_updated",
                        ]
                    )
                    token = locked.get_access_token_secret()
                account.access_token = locked.access_token
                account.refresh_token = locked.refresh_token
                account.token_expires_at = locked.token_expires_at
        except GraphAuthorizationRequired:
            self._record_authorization_failure()
            raise
        return token

    def _check_authorization_binding(self, current: "EmailAccount") -> None:
        """Reject stale adapters after disconnection, reconnection, or credential edits."""
        account = self.email_account
        fields = (
            "provider",
            "email_address",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
        )
        if any(
            getattr(current, field) != getattr(account, field) for field in fields
        ) or any(
            current.extra_settings.get(key) != account.extra_settings.get(key)
            for key in ("authorization_revision", "graph_user_id", "graph_tenant_id")
        ):
            raise GraphRequestError(
                "This mailbox authorization changed. Reload the account before trying again."
            )
        if current.status != current.Status.ACTIVE:
            raise GraphAuthorizationRequired(
                "Reconnect the Microsoft account to restore mailbox access."
            )
        if (
            current.extra_settings.get("graph_configuration_digest")
            != self._grant_fingerprint()
        ):
            raise GraphAuthorizationRequired(
                "The mailbox credentials changed. Reconnect the Microsoft account."
            )

    def _record_authorization_failure(self) -> None:
        """Stop polling only the failed grant, leaving concurrent reconnections intact."""
        account = self.email_account
        if account._state.adding:
            return
        error = "Reconnect the Microsoft account to restore mailbox access."
        updated = (
            type(account)
            .objects.filter(
                pk=account.pk,
                status=account.Status.ACTIVE,
                access_token=account.access_token,
                refresh_token=account.refresh_token,
                oauth_client_id=account.oauth_client_id,
                oauth_client_secret=account.oauth_client_secret,
                oauth_tenant_id=account.oauth_tenant_id,
                extra_settings=account.extra_settings,
            )
            .update(
                status=account.Status.ERROR,
                sync_enabled=False,
                next_sync_at=None,
                validation_error=error,
                datetime_updated=timezone.now(),
            )
        )
        if updated:
            account.status = account.Status.ERROR
            account.sync_enabled = False
            account.next_sync_at = None
            account.validation_error = error

    def _graph_url(self, path: str) -> str:
        """Reject pagination links that could disclose tokens to another origin."""
        url = f"{GRAPH_ROOT}{path}" if path.startswith("/") else path
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc != "graph.microsoft.com"
            or not parts.path.startswith("/v1.0/")
            or parts.fragment
        ):
            raise GraphRequestError(
                "Microsoft returned an invalid mailbox continuation link."
            )
        return url

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        """Respect Retry-After without keeping a worker asleep for an unbounded period."""
        value = response.headers.get("Retry-After", "")
        try:
            delay = float(value)
        except ValueError:
            try:
                deadline = parsedate_to_datetime(value)
                delay = (deadline - timezone.now()).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = float(2**attempt)
        if delay > MAX_RETRY_WAIT:
            raise GraphRequestError(
                "Microsoft is throttling mailbox requests. Synchronization will retry later.",
                status_code=429,
            )
        return max(0, delay)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
        data: str | None = None,
        retry: bool = True,
    ) -> requests.Response:
        """Issue bounded Graph requests with immutable IDs and safe error messages."""
        url = self._graph_url(path)
        token = self._access_token()
        authenticated_retry = False
        for attempt in range(3 if retry else 1):
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Prefer": 'IdType="ImmutableId"',
                        "Content-Type": "text/plain"
                        if data is not None
                        else "application/json",
                    },
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                if retry and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                message = (
                    "Microsoft mailbox requests are temporarily unavailable. Try again."
                )
                if not retry:
                    message = "Microsoft did not confirm this operation. Check the mailbox before sending again."
                raise GraphRequestError(message) from exc
            if 200 <= response.status_code < 300:
                return response
            if (
                response.status_code == 401
                and retry
                and not authenticated_retry
                and attempt < 2
            ):
                token = self._access_token(rejected_token=token)
                authenticated_retry = True
                continue
            if (
                retry
                and response.status_code in {429, 500, 502, 503, 504}
                and attempt < 2
            ):
                time.sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code in {400, 404, 410}:
                try:
                    error = response.json().get("error", {})
                except (ValueError, AttributeError):
                    error = {}
                if (
                    isinstance(error, dict)
                    and str(error.get("code", "")).casefold() == "syncstatenotfound"
                ):
                    raise GraphRequestError(
                        "The Microsoft synchronization cursor expired.",
                        status_code=response.status_code,
                        cursor_expired=True,
                    )
            errors = {
                401: "Reconnect the Microsoft account to restore mailbox access.",
                403: "Microsoft denied mailbox access. Check consent and mailbox permissions.",
                404: "The Microsoft mailbox item is no longer available.",
                410: "The Microsoft synchronization cursor expired.",
                413: "This message exceeds Microsoft's upload limit. Reduce its attachment size.",
                429: "Microsoft is throttling mailbox requests. Try again later.",
            }
            if response.status_code in {401, 403}:
                self._record_authorization_failure()
                raise GraphAuthorizationRequired(
                    errors[response.status_code], status_code=response.status_code
                )
            raise GraphRequestError(
                errors.get(
                    response.status_code,
                    "Microsoft could not complete the mailbox operation.",
                ),
                status_code=response.status_code,
            )
        raise GraphRequestError("Microsoft could not complete the mailbox operation.")

    def _json_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Decode object responses without exposing malformed provider content."""
        response = self._request(method, path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            result = response.json()
        except ValueError as exc:
            raise GraphRequestError(
                "Microsoft returned an invalid mailbox response."
            ) from exc
        if not isinstance(result, dict):
            raise GraphRequestError("Microsoft returned an invalid mailbox response.")
        return result

    def _collection(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Follow validated Graph pages, optionally stopping at a requested result limit."""
        items: list[dict[str, Any]] = []
        visited: set[str] = set()
        while path and path not in visited:
            visited.add(path)
            page = self._json_request("GET", path, params=params)
            items.extend(page.get("value", []))
            if limit is not None and len(items) >= limit:
                return items[:limit]
            path = str(page.get("@odata.nextLink") or "")
            params = None
        return items

    def validate_connection(self) -> list[str]:
        """Check verified mailbox access and discover folders without sending mail."""
        self._verify_identity()
        return self.list_mailboxes()

    def list_mailboxes(self) -> list[str]:
        """Discover nested stable folder IDs with localized labels and well-known roles."""
        roles = {
            "main_folder": self._json_request(
                "GET", "/me/mailFolders/inbox", params={"$select": "id"}
            )["id"],
            "sent_folder": self._json_request(
                "GET", "/me/mailFolders/sentitems", params={"$select": "id"}
            )["id"],
        }
        folders = self._collection(
            "/me/mailFolders",
            params={"$top": 100, "$select": "id,displayName,childFolderCount"},
        )
        discovered: dict[str, dict[str, Any]] = {}
        for folder in folders:
            folder_id = str(folder["id"])
            if folder_id in discovered:
                continue
            previous = (self.email_account.mailboxes or {}).get(folder_id, {})
            discovered[folder_id] = {
                "label": previous.get("label") or folder["displayName"],
                "color": previous.get("color", ""),
                **{role: folder_id == role_id for role, role_id in roles.items()},
            }
            if folder.get("childFolderCount"):
                folders.extend(
                    self._collection(
                        f"/me/mailFolders/{quote(folder_id, safe='')}/childFolders",
                        params={
                            "$top": 100,
                            "$select": "id,displayName,childFolderCount",
                        },
                    )
                )
        self._mailbox_defaults = discovered
        return list(discovered)

    def mailbox_defaults(self) -> dict[str, dict[str, Any]]:
        """Expose stable folder IDs and localized roles after connection discovery."""
        return {
            folder_id: dict(settings)
            for folder_id, settings in self._mailbox_defaults.items()
        }

    def mark_as_read(self, email_id: str, *, mailbox: str = "INBOX") -> None:
        """Apply an idempotent read flag using the account-wide immutable ID."""
        self._request(
            "PATCH",
            f"/me/messages/{quote(email_id, safe='')}",
            json_body={"isRead": True},
        )

    def delete_email(self, email_id: str, *, mailbox: str = "INBOX") -> None:
        """Delete a message without retrying a potentially completed mutation."""
        self._request("DELETE", f"/me/messages/{quote(email_id, safe='')}", retry=False)

    def send_email(
        self,
        *,
        to: list[str],
        subject: str,
        body_html: str | None,
        body_text: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[EmailAttachment] | None = None,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> EmailSendResult:
        """Send a MIME draft once and return its stable Graph ID for Sent reconciliation."""
        if not to:
            raise ValidationError("At least one recipient is required.")
        message = EmailMessage(policy=SMTP)
        message["From"] = self.email_account.email_address
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message_id = make_msgid()
        message["Message-ID"] = message_id
        for header, value in (
            ("Cc", ", ".join(cc or [])),
            ("Bcc", ", ".join(bcc or [])),
            ("Reply-To", reply_to),
            ("In-Reply-To", in_reply_to),
            ("References", " ".join(references or [])),
        ):
            if value:
                message[header] = value
        message.set_content(body_text or strip_tags(body_html or ""))
        if body_html:
            message.add_alternative(body_html, subtype="html")
        html_part = message.get_body(preferencelist=("html",))
        for attachment in attachments or []:
            if attachment.calendar_method:
                from bloomerp.communication.calendar.mime import (
                    add_calendar_alternative,
                )

                add_calendar_alternative(message, attachment)
                continue
            maintype, _, subtype = attachment.content_type.partition("/")
            if attachment.disposition == "inline":
                if html_part is None or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-]+", attachment.content_id):
                    raise ValidationError("Inline images require an HTML body and a valid Content-ID.")
                if maintype != "image":
                    raise ValidationError("Inline email parts must be images.")
                html_part.add_related(
                    attachment.content, maintype=maintype, subtype=subtype,
                    filename=attachment.filename, disposition="inline",
                    cid=f"<{attachment.content_id}>",
                )
                continue
            message.add_attachment(
                attachment.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )
        payload = base64.b64encode(message.as_bytes()).decode("ascii")
        if len(payload) > 4 * 1024 * 1024:
            raise ValidationError(
                "This message exceeds the 4 MB upload limit. Reduce its attachment size."
            )
        draft = self._json_request("POST", "/me/messages", data=payload, retry=False)
        draft_id = str(draft.get("id") or "")
        if not draft_id:
            raise GraphRequestError(
                "Microsoft did not confirm the draft. Check Drafts before trying again."
            )
        result = EmailSendResult(
            provider_message_id=draft_id,
            message_id=draft.get("internetMessageId") or message_id,
            mailbox=next(
                (
                    folder_id
                    for folder_id, settings in self.email_account.mailboxes.items()
                    if settings.get("sent_folder")
                ),
                "sentitems",
            ),
        )
        try:
            self._request(
                "POST", f"/me/messages/{quote(draft_id, safe='')}/send", retry=False
            )
        except GraphRequestError as exc:
            if exc.status_code == 0 or exc.status_code >= 500:
                raise EmailSendUnconfirmed(result) from exc
            raise
        return result

    def fetch_email_content(self, email_id: str, *, mailbox: str = "INBOX") -> str:
        """Retrieve HTML content, escaping plaintext bodies before displaying them."""
        message = self._json_request(
            "GET",
            f"/me/messages/{quote(email_id, safe='')}",
            params={"$select": "body"},
        )
        body = message.get("body") or {}
        content = str(body.get("content") or "")
        return (
            content
            if str(body.get("contentType", "")).casefold() == "html"
            else f"<pre>{escape(content)}</pre>"
        )

    def fetch_email_attachment(
        self, email_id: str, attachment_id: str, *, mailbox: str = "INBOX"
    ) -> EmailAttachment | None:
        """Retrieve a file or attached message without following remote reference links."""
        path = f"/me/messages/{quote(email_id, safe='')}/attachments/{quote(attachment_id, safe='')}"
        attachment = self._json_request("GET", path)
        kind = attachment.get("@odata.type", "")
        if kind == "#microsoft.graph.referenceAttachment":
            return None
        if kind == "#microsoft.graph.itemAttachment":
            content = self._request("GET", f"{path}/$value").content
            content_type = "message/rfc822"
        else:
            try:
                content = base64.b64decode(
                    attachment.get("contentBytes", ""), validate=True
                )
            except ValueError as exc:
                raise GraphRequestError(
                    "Microsoft returned an invalid attachment."
                ) from exc
            content_type = attachment.get("contentType") or "application/octet-stream"
        return EmailAttachment(
            filename=attachment.get("name") or "attachment",
            content=content,
            content_type=content_type,
        )

    def _addresses(self, recipients: list[dict[str, Any]]) -> list[str]:
        """Extract canonical addresses from Graph recipient objects."""
        return [
            str(item["emailAddress"]["address"])
            for item in recipients
            if item.get("emailAddress", {}).get("address")
        ]

    def _email(self, message: dict[str, Any], *, mailbox: str) -> BloomerpEmail:
        """Map provider fields and attachment references to the neutral email index."""
        sender = (message.get("from") or {}).get("emailAddress") or {}
        headers = {
            item["name"].casefold(): item["value"]
            for item in message.get("internetMessageHeaders", [])
        }
        attachments: list[EmailAttachmentMetadata] = []
        calendar_candidate = str(message.get("@odata.type", "")).startswith(
            "#microsoft.graph.eventMessage"
        )
        if message.get("hasAttachments"):
            for attachment in self._collection(
                f"/me/messages/{quote(message['id'], safe='')}/attachments",
                params={"$select": "id,name,contentType,size"},
            ):
                if str(attachment.get("contentType") or "").split(";", 1)[
                    0
                ].casefold() in {
                    "text/calendar",
                    "application/ics",
                    "application/icalendar",
                }:
                    calendar_candidate = True
                if (
                    attachment.get("@odata.type")
                    != "#microsoft.graph.referenceAttachment"
                ):
                    attachments.append(
                        EmailAttachmentMetadata(
                            id=attachment["id"],
                            filename=attachment.get("name") or "attachment",
                            content_type=attachment.get("contentType")
                            or "application/octet-stream",
                            size=attachment.get("size") or 0,
                        )
                    )
        is_read = bool(message.get("isRead"))
        return BloomerpEmail(
            provider=self.email_account.provider,
            provider_message_id=message["id"],
            provider_message_id_scope="account",
            email_account_id=str(self.email_account.pk),
            mailbox=mailbox,
            subject=message.get("subject") or "",
            sender=formataddr((sender.get("name") or "", sender.get("address") or "")),
            to=self._addresses(message.get("toRecipients", [])),
            cc=self._addresses(message.get("ccRecipients", [])),
            reply_to=self._addresses(message.get("replyTo", [])),
            date=parse_datetime(
                message.get("receivedDateTime") or message.get("sentDateTime") or ""
            ),
            message_id=message.get("internetMessageId"),
            in_reply_to=headers.get("in-reply-to"),
            references=headers.get("references", "").split(),
            is_read=is_read,
            is_draft=bool(message.get("isDraft")),
            flags=[r"\Seen"] if is_read else [],
            snippet=message.get("bodyPreview") or "",
            raw={
                "parent_folder_id": message.get("parentFolderId"),
                "is_draft": bool(message.get("isDraft")),
            },
            attachments=attachments,
            calendar_parts=self._calendar_parts(message["id"])
            if calendar_candidate
            else [],
        )

    def _calendar_parts(self, message_id: str) -> list[CalendarEmailPart]:
        """Decode candidate scheduling MIME through the existing bounded calendar parser."""
        from bloomerp.communication.calendar.mime import extract_calendar_parts

        response = self._request(
            "GET", f"/me/messages/{quote(message_id, safe='')}/$value"
        )
        return extract_calendar_parts(message_from_bytes(response.content))

    def search_emails(
        self, query: str | None = None, *, mailbox: str = "INBOX", limit: int = 50
    ) -> list[BloomerpEmail]:
        """Search one folder and return bounded immutable-ID results."""
        if limit <= 0:
            return []
        params: dict[str, str | int] = {
            "$top": min(limit, 100),
            "$select": MESSAGE_FIELDS,
        }
        if query:
            params["$search"] = (
                '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"'
            )
        else:
            params["$orderby"] = "receivedDateTime desc"
        messages = self._collection(
            f"/me/mailFolders/{quote(mailbox, safe='')}/messages",
            params=params,
            limit=limit,
        )
        return [self._email(message, mailbox=mailbox) for message in messages]

    def sync_emails(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        *,
        mailbox: str = "INBOX",
    ) -> list[BloomerpEmail]:
        """Provide bounded date-filtered reads for callers outside durable synchronization."""
        if limit <= 0:
            return []
        params: dict[str, str | int] = {
            "$top": min(limit, 100),
            "$select": MESSAGE_FIELDS,
            "$orderby": "receivedDateTime desc",
        }
        filters = []
        if from_date:
            filters.append(f"receivedDateTime ge {self._timestamp(from_date)}")
        if to_date:
            filters.append(f"receivedDateTime le {self._timestamp(to_date)}")
        if filters:
            params["$filter"] = " and ".join(filters)
        messages = self._collection(
            f"/me/mailFolders/{quote(mailbox, safe='')}/messages",
            params=params,
            limit=limit,
        )
        return [self._email(message, mailbox=mailbox) for message in messages]

    def _timestamp(self, value: date | datetime) -> str:
        """Format date filters as UTC timestamps accepted by Graph."""
        if not isinstance(value, datetime):
            value = datetime.combine(
                value, datetime.min.time(), tzinfo=UTC
            )
        if timezone.is_naive(value):
            value = timezone.make_aware(value, UTC)
        return (
            value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        )

    def sync_batch(
        self,
        *,
        mailbox: str = "INBOX",
        cursor: dict[str, Any] | None = None,
        limit: int = 50,
        from_date: date | datetime | None = None,
        to_date: date | datetime | None = None,
    ) -> EmailSyncBatch:
        """Read one durable delta page, preserving tombstones and read-state updates."""
        state = dict(cursor or {})
        path = state.get("next_link") or state.get("delta_link")
        reset = not path
        params: dict[str, str | int] | None = None
        if not path:
            path = f"/me/mailFolders/{quote(mailbox, safe='')}/messages/delta"
            params = {"$top": max(1, min(limit, 100)), "$select": MESSAGE_FIELDS}
        try:
            page = self._json_request("GET", path, params=params)
        except GraphRequestError as exc:
            if (exc.status_code != 410 and not exc.cursor_expired) or not state:
                raise
            # An expired delta token requires a complete scan; replay is idempotent.
            reset = True
            page = self._json_request(
                "GET",
                f"/me/mailFolders/{quote(mailbox, safe='')}/messages/delta",
                params={"$top": max(1, min(limit, 100)), "$select": MESSAGE_FIELDS},
            )
        next_link = page.get("@odata.nextLink")
        delta_link = page.get("@odata.deltaLink")
        if not next_link and not delta_link:
            raise GraphRequestError(
                "Microsoft did not return a synchronization continuation."
            )
        for link in (next_link, delta_link):
            if link:
                self._graph_url(link)
        messages: list[BloomerpEmail] = []
        deleted: list[str] = []
        for message in page.get("value", []):
            if "@removed" in message:
                deleted.append(message["id"])
                try:
                    moved = self._json_request(
                        "GET",
                        f"/me/messages/{quote(message['id'], safe='')}",
                        params={"$select": MESSAGE_FIELDS},
                    )
                except GraphRequestError as exc:
                    if exc.status_code != 404:
                        raise
                else:
                    destination = moved.get("parentFolderId")
                    if not destination:
                        raise GraphRequestError(
                            "Microsoft did not identify the message's current folder."
                        )
                    messages.append(self._email(moved, mailbox=str(destination)))
                continue
            # Delta may emit only a read-state change; fetch the full index fields.
            if not {"subject", "from", "isRead"}.issubset(message):
                try:
                    message = self._json_request(
                        "GET",
                        f"/me/messages/{quote(message['id'], safe='')}",
                        params={"$select": MESSAGE_FIELDS},
                    )
                except GraphRequestError as exc:
                    if exc.status_code != 404:
                        raise
                    deleted.append(message["id"])
                    continue
            messages.append(self._email(message, mailbox=mailbox))
        return EmailSyncBatch(
            messages=messages,
            deleted_message_ids=deleted,
            cursor={"next_link": next_link}
            if next_link
            else {"delta_link": delta_link},
            has_more=bool(next_link),
            reset=reset,
        )
