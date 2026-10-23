# Email providers

Email integrations are registered with `EMAIL_PROVIDER_REGISTRY` in
`bloomerp.communication.builtins.emails.registry`. Each
`EmailProviderDefinition` describes setup, authorization, synchronization and an
adapter class. Import the neutral contracts from
`bloomerp.communication.builtins.emails.provider_definition`. Account creation,
reconfiguration, mailbox mapping, the inbox,
email actions and scheduled synchronization all resolve that definition.

Keep service-specific endpoints, credentials, payloads and error translation in
the adapter. Shared views and jobs must dispatch through the definition instead
of branching on a provider key. A new integration should not need its own
account-creation view, callback view or background scheduler.

## Register a provider

Register the definition once during your application's startup, after Django
has loaded its applications. A symbolic registry key is used for attribute
access; the definition's stable `key` is stored on `EmailAccount.provider`.
Both keys must be unique. The registry resolves either form, and the account
model's callable choices include registrations made after model import.

```python
from django.apps import AppConfig


class MailIntegrationConfig(AppConfig):
    """Register the application's reusable email integration."""

    name = "mail_integration"

    def ready(self) -> None:
        """Expose the provider through the shared email registry."""
        from bloomerp.communication.builtins.emails.registry import (
            EMAIL_PROVIDER_REGISTRY,
        )
        from mail_integration.email_provider import EMAIL_PROVIDER

        EMAIL_PROVIDER_REGISTRY.register("CUSTOM_MAIL", EMAIL_PROVIDER)
```

`EMAIL_PROVIDER` is an `EmailProviderDefinition` constructed in your integration
module. Its adapter must subclass `BaseEmailAdapter`.

## Definition reference

| Field | Contract |
| --- | --- |
| `key` | Stable identifier persisted on accounts and email metadata. Do not change it after accounts have been created. |
| `name`, `description`, `icon` | Provider selection labels and Font Awesome icon class. |
| `adapter_class` | `BaseEmailAdapter` subclass initialized with `email_account=account`. |
| `fields` | Setup field names supported by `EmailAccountSettingsForm`. |
| `required_fields` | Subset of setup fields that must be supplied. Required stored secrets may remain blank during reconfiguration to preserve their current values. |
| `initial` | Defaults for setup fields. Wizard values override these defaults. |
| `setup_instructions` | Optional trusted setup HTML rendered with the settings form. |
| `sync_capabilities` | An `EmailSyncCapability` describing the default mode, supported modes and polling interval. |
| `authorization` | Optional `EmailAuthorizationDefinition` enabling the shared consent, callback, reconnect and disconnect lifecycle. `None` keeps direct connection validation. |
| `mailbox_defaults` | Optional callable receiving the adapter and returning mailbox settings keyed by remote identifier: `dict[str, dict[str, Any]]`. Use this for provider-discovered folder roles and labels. |

Use account fields for user-supplied connection settings. The existing OAuth
fields are `oauth_client_id`, `oauth_client_secret`, `oauth_tenant_id` and
`oauth_scopes`. An integration must not require an instance-wide environment
variable for credentials that the account creator supplies.

`EmailSyncCapability.default_mode` defaults to `EmailSyncMode.POLLING`,
`supported_modes` defaults to polling only, and
`default_poll_interval_minutes` defaults to five. Only declare modes that the
integration actually implements. Declaring `PUSH` does not create a webhook or
subscription lifecycle.

`mailbox_defaults` returns the same mapping accepted by `EmailAccount.mailboxes`:
each entry can contain `label`, `main_folder`, `sent_folder` and `color`.
Identify standard folders through the remote service's stable role identifiers
when available. Do not infer a folder's role from its translated display name.
The setup flow merges defaults with the user's existing mailbox settings.

## Shared authorization

Set `authorization=EmailAuthorizationDefinition(...)` to opt in. Supply these
hooks with the exact protocol signatures from `provider_definition.py`:

| Hook | Signature and result |
| --- | --- |
| `start` | `(adapter: BaseEmailAdapter, *, redirect_uri: str, state: str, code_verifier: str) -> str`; return the provider consent URL. |
| `complete` | `(adapter: BaseEmailAdapter, *, code: str, redirect_uri: str, code_verifier: str) -> None`; exchange the authorization code, verify the remote mailbox identity and populate credentials on `adapter.email_account`. |
| `disconnect` | Optional `(adapter: BaseEmailAdapter) -> None`; revoke provider-side authorization where supported. |
| `prepare` | Optional `(adapter: BaseEmailAdapter) -> None`; persist any refreshed authorization before a caller starts its business transaction. |
| `label` | Action label shown to the user; defaults to `Connect account`. |

The hooks can be named functions or compatible unbound adapter methods. Their
implementation belongs to the provider module. A definition can wire existing
hooks like this:

```python
from bloomerp.communication.builtins.emails.provider_definition import (
    EmailAuthorizationDefinition,
    EmailProviderDefinition,
)
from mail_integration.adapter import CustomMailAdapter
from mail_integration.authorization import complete_authorization, start_authorization


EMAIL_PROVIDER = EmailProviderDefinition(
    key="custom_mail",
    name="Custom Mail",
    description="Connect your mailbox.",
    icon="fa-solid fa-envelope",
    adapter_class=CustomMailAdapter,
    fields=["name", "email_address", "oauth_client_id", "oauth_client_secret"],
    required_fields=["email_address", "oauth_client_id", "oauth_client_secret"],
    authorization=EmailAuthorizationDefinition(
        start=start_authorization,
        complete=complete_authorization,
    ),
)
```

The framework supplies state, a PKCE verifier and the callback URI. The start
hook must derive an S256 challenge from that verifier and send the unchanged
state and callback URI to the authorization service. The complete hook must
send the same verifier and callback URI when exchanging the code. Request only
the scopes the adapter needs, including offline access if background refresh
requires a separate grant. Do not parse an unverified token as proof of mailbox
identity; query the authenticated service and compare it with the requested
account before accepting authorization.

The shared callback route is named `email_authorization_callback`, with path
`communication/email/authorize/callback/`. Always use Django URL reversal for
its deployment-specific path. The callback origin must use HTTPS and an exact
host in Django's `ALLOWED_HOSTS`; wildcard host acceptance is insufficient for
this redirect. Register the complete displayed callback URI with the remote
service, including its scheme, path and trailing slash.

The lifecycle stores expiring, encrypted setup data and a PKCE verifier in a
private `EmailAuthorizationRequest`, bound to the initiating user, browser
session, account and callback origin. The callback atomically consumes state
before token exchange, so it cannot be replayed. The shared lifecycle owns
permission checks and continues the existing mailbox-mapping wizard after
successful consent. The provider hook must not save a candidate account before
the wizard finishes.

Reconfiguration starts the same authorization flow when needed. Disconnect
uses the shared account action to clear credentials and stop synchronization;
the optional provider hook then receives an unsaved snapshot of the original
account credentials for remote revocation. Local revocation remains effective
if the remote hook fails. Do not persist that snapshot or restore its tokens.
Local email history is retained. This registration does not install webhooks: extend the neutral
definition and shared dispatch path if a future integration needs them.

Calendar sending resolves an accessible account and invokes `prepare` before
opening its scheduling transaction. A provider with rotating refresh tokens can
renew and persist its grant here, independently of any later scheduling rollback.
The send path then locks the account before the event and revalidates the actual
sender. A provider must not refresh a rotating grant inside a caller's transaction
that could roll back its persisted token; require preparation outside that
transaction, and fail safely if the prepared grant expires before use. This
optional hook belongs to the definition and must not install a separate runner.

## Adapter contract

The adapter receives an `EmailAccount`, which can be unsaved during setup.
Connection validation discovers provider mailbox identifiers before the user
maps those mailboxes into the inbox. Treat mailbox identifiers as opaque; users
can assign separate display labels, a main mailbox and a sent mailbox.

| Method | Responsibility |
| --- | --- |
| `validate_connection() -> list[str]` | Validate the account and return available mailbox identifiers. |
| `list_mailboxes() -> list[str]` | Discover mailbox identifiers without changing their local labels or assignments. |
| `sync_emails(...) -> list[BloomerpEmail]` | Fetch a bounded set of provider-neutral email index records. |
| `sync_batch(...) -> EmailSyncBatch` | Fetch one durable synchronization page and its next opaque cursor. The default implementation wraps `sync_emails()`. |
| `search_emails(...) -> list[BloomerpEmail]` | Search remote messages within a mailbox, respecting the supplied limit. |
| `fetch_email_content(email_id, *, mailbox) -> str` | Fetch a message body on demand. |
| `fetch_email_attachment(email_id, attachment_id, *, mailbox) -> EmailAttachment \| None` | Fetch one attachment referenced by indexed metadata. |
| `mark_as_read(email_id, *, mailbox) -> None` | Update the remote read state. |
| `delete_email(email_id, *, mailbox) -> None` | Apply the provider's message deletion behavior. |
| `send_email(...) -> str \| EmailSendResult` | Send content, recipients, threading headers and attachments; return an RFC Message-ID or the typed result described below. |

An optional `close() -> None` releases network resources; shared callers invoke
it after use. All adapter methods and helpers should have explicit parameter and
return annotations and descriptive docstrings.

`BloomerpEmail.provider_message_id` is a remote retrieval identifier.
`BloomerpEmail.message_id` is the RFC Message-ID used to match copies of the same
message. They are not interchangeable. Supply `email_account_id`, `mailbox`,
threading metadata, read state, attachment references and calendar MIME parts
when available. Store only the extra provider metadata needed to retrieve or
reconcile a message in `raw`; never put access tokens or client secrets there.

Inbound attachment metadata contains an identifier, filename, content type and
size. The inbox downloads attachment bytes on demand. Outgoing
`EmailAttachment` contains bytes and can also declare a calendar method. Keep
provider upload limits and MIME conversion inside the adapter, and reject
unsupported payloads before creating remote side effects.

### Outbound results

Legacy adapters may return an RFC Message-ID string. Return `EmailSendResult`
when the service also supplies a durable remote retrieval identifier. A returned
result means the provider accepted the message for processing, not that the
recipient received it. The composer says "accepted for sending" and workflow
nodes return `status="accepted"` with both available identifiers. An HTTP 202
response must not be presented as final delivery.

| Field | Meaning |
| --- | --- |
| `provider_message_id` | Remote message identifier used for retrieval and later reconciliation. |
| `message_id` | Optional RFC Message-ID used for reply headers and threading. |
| `mailbox` | Remote mailbox identifier, defaulting to `"Sent"`. |
| `provider_message_id_scope` | `"account"` for stable IDs across mailbox moves, or `"mailbox"` for mailbox-local IDs. Defaults to `"account"`. |

Never return a remote retrieval ID as an RFC Message-ID string. The shared
outbound helpers preserve both identities so a later Sent-folder sync can
reuse the local reply even if the service rewrites its RFC Message-ID.

If a remote send might have completed but its response was lost, raise
`EmailSendUnconfirmed(result)` with the known remote identity. Do not retry
non-idempotent send or draft-creation requests automatically. The composer
stores pending correlation, shows an actionable warning and prevents repeating
the same submitted draft. Workflow nodes record an `unconfirmed` status and
the identifiers. Calendar actions retain the remote identity when scheduling
changes roll back and block further sends for that event until synchronization
confirms delivery. Retrying the same calendar revision after confirmation
finishes the local update without sending the message again.

Populate `BloomerpEmail.is_draft` during synchronization. A remote non-draft
update clears a matching pending-send marker; a draft update retains it. This
keeps provider transport details out of shared message reconciliation.

## Durable polling

Override `BaseEmailAdapter.sync_batch()` when the remote API exposes page or
delta cursors. Its keyword-only arguments are `mailbox: str = "INBOX"`,
`cursor: dict[str, Any] | None = None`, `limit: int = 50`,
`from_date: date | datetime | None = None` and
`to_date: date | datetime | None = None`. Return an `EmailSyncBatch`:

| Field | Meaning |
| --- | --- |
| `messages` | Index records created or changed in this page. |
| `deleted_message_ids` | Remote IDs removed from this page's mailbox. |
| `cursor` | JSON-serializable state to save after the page is applied; `None` leaves the existing cursor unchanged. |
| `has_more` | Whether another page must be fetched immediately. The limit is a page size, not a cap on a complete sync. |
| `reset` | Whether this is the first page of a complete mailbox snapshot, including recovery after an invalid cursor. Defaults to `False`. |

The shared polling handler stores cursors under
`EmailAccount.sync_cursor["mailboxes"][mailbox]`. Each page's cursor and changes
to all linked inbox folders commit in one transaction. Do not save cursor
progress in the adapter: if local persistence fails, the old cursor must remain
available for retry. Return empty message lists for pages that contain only
deletions or advance a cursor. Validate continuation URLs before sending
credentials to them, and handle expired remote cursors by restarting the
provider's documented synchronization flow.

Set `reset=True` only on the first page of a full snapshot. The reconciler stages
existing mailbox locations as potential removals and cancels those removals as
IDs appear across later pages. It removes unseen locations after the selected
mailbox synchronization finishes. This also reconciles deletions that happened
while an incremental cursor was invalid. Pending removals and newly created
delivery references survive an interruption alongside the cursor.

For remote IDs that survive mailbox moves, set
`BloomerpEmail.provider_message_id_scope="account"`. The default `"mailbox"`
keeps IDs scoped to their original mailbox. The shared reconciler uses an
account-scoped ID to correlate copies or moves without treating them as newly
received messages. Removal IDs are always scoped to the mailbox being polled.
Pending removals are reconciled after all selected mailboxes complete, so a
source-folder removal cannot discard a message before its destination-folder
update is applied. Interrupted runs retain pending removals for retry.

The scheduler dispatches only active, enabled polling accounts and respects the
account interval. Account locks prevent simultaneous ordinary runs, while the
transactional cursor and idempotent message upserts protect page retries.
Existing providers that implement only `sync_emails()` retain the same bounded
fetch behavior through the default batch wrapper.

A manual synchronization with `from_date` or `to_date` uses the bounded
`sync_emails()` path and leaves the incremental cursor unchanged. Unbounded
manual synchronization and scheduled polling use `sync_batch()` and exhaust
its pages. A date-filtered import must never advance a complete-mailbox delta
cursor or remove messages outside its requested range.

## Credential handling

Use `EmailAccount.get_secret()` and `set_secret()` or the named token/client
secret helpers. The account encrypts `password`, `oauth_client_secret`,
`access_token` and `refresh_token` with the existing communications encryption
key. Retain that key across deployments so stored credentials remain readable.
Never log token responses, authorization codes, secret field values or raw
provider errors that may contain them.

Token refresh belongs to the adapter. Refresh before expiry, save token rotation
atomically for persisted accounts, and avoid overwriting newer account settings
with a stale adapter instance. A revoked or expired grant must require renewed
authorization rather than repeatedly retrying the same invalid refresh token.

## Focused coverage

Read the [testing guide](testing/index.md) and the relevant layer guide before
adding tests. Generate cases for any new model, view or component with
`generate_test_cases`, then add declarative scenarios to those generated files.
Keep lifecycle coverage with the account or shared authorization endpoint that
owns it; keep transport behavior with existing email integration tests.

Useful cases include an extension registration, a setup/authorization round
trip, rejected or replayed state, token rotation, a failed synchronization batch
that retains its previous cursor, message identity across mailbox moves, and
attachment retrieval. Mock remote transport and assert externally observable
behavior. Do not duplicate those assertions across every layer.
