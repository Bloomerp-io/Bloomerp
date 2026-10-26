# Connect a Microsoft 365 mailbox

Choose **Microsoft 365 / Outlook** when creating an email account to connect
your own Microsoft 365 mailbox through delegated Microsoft Graph access.
Supply the app registration's client ID, client secret and tenant ID in the
account-creation form. Each account stores its own credentials; there are no
provider client credentials to configure in environment variables.

This version supports an organizational mailbox in Microsoft's commercial
cloud. It uses polling, including incremental message changes and deletions.
It does not support personal Outlook.com accounts, shared mailboxes, send-as
aliases, on-premises Exchange or national-cloud Graph endpoints.

## Register the application

1. Open **Microsoft Entra admin center → App registrations → New registration**
   in the mailbox's directory. Choose **Accounts in this organizational
   directory only** for the supported single-tenant setup.
2. Copy the **Application (client) ID** and **Directory (tenant) ID**. The tenant
   value entered in Bloomerp must be the directory UUID.
3. Under **Authentication**, add a **Web** platform redirect URI. Copy the full
   callback URL shown in Bloomerp's email-account settings. With the default URL
   configuration it is
   `https://your-instance.example/communication/email/authorize/callback/`.
   Preserve the trailing slash. The public HTTPS host must be explicitly
   present in the instance's `ALLOWED_HOSTS` configuration. A wildcard entry is
   insufficient for this callback.
4. Under **Certificates & secrets**, create a client secret. Copy its **Value**,
   which is shown only when it is created, and record the expiry date. Enter the
   value in Bloomerp's client-secret field, not the secret's identifier.
5. Under **API permissions → Microsoft Graph → Delegated permissions**, add
   `User.Read`, `Mail.ReadWrite` and `Mail.Send`. The authorization flow also
   requests `offline_access` so background synchronization can refresh access.
   Complete administrator consent if required by your tenant's consent policy.

Use the Web registration type because Bloomerp exchanges authorization codes on
the server with the client secret and PKCE. The callback must match the
registered URI. See Microsoft's [app registration guide](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app),
[redirect URI requirements](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)
and [authorization-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).

`Mail.ReadWrite` provides mailbox access and mutation but does not include
sending. `Mail.Send` grants sending, and `User.Read` lets Bloomerp verify which
mailbox was authorized. Use delegated permissions for this integration. See the
[Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference).

## Create the account

1. In Bloomerp, open **Communication → Create an email account**, then choose
   **Microsoft 365 / Outlook**.
2. Enter a label, the mailbox email address, client ID, client-secret value and
   directory tenant ID. Use the mailbox's primary address or user principal
   name; the signed-in account must match it.
3. Continue to Microsoft and sign in with that mailbox. Approve the requested
   permissions. Return in the same browser session so Bloomerp can validate the
   authorization attempt.
4. Review the discovered mailboxes, labels and main/sent roles. Bloomerp uses
   stable folder IDs and Microsoft's standard folder roles, so translated folder
   names remain usable. Finish the wizard, then add an **Emails** folder to the
   intended Bloomerp inbox and select this email account as its source.
5. Leave synchronization enabled to use the default five-minute polling
   interval, or adjust the account's interval. Scheduled polling requires the
   instance's existing inbox event-source worker and scheduler. Manual
   synchronization uses the same adapter. Leave both date filters blank for a
   complete incremental sync; a date-bounded import honors its message limit and
   leaves the normal polling cursor unchanged.

Client secrets, access tokens and refresh tokens use Bloomerp's existing
encrypted email-secret storage. The instance must retain its communications
encryption key across deployments. Setup performs mailbox validation without
sending a test message.

## Reconnect and disconnect

Open **Reconfigure email account** to renew consent or rotate the client secret.
A blank secret field retains the current stored value. Authorize the original
Microsoft mailbox and tenant again; changing the identity requires creating a
separate email account.

Disconnect stops account synchronization and removes Bloomerp's stored access
and refresh tokens while retaining imported email history. It does not revoke
the app's consent in Microsoft Entra. To remove that grant as well, revoke it in
your Microsoft account or tenant administration.

Expired client secrets, revoked refresh tokens and changed tenant policies may
require reconnection. Check the account's validation or synchronization error,
update the app registration if needed, then repeat authorization. If consent
is denied or the attempt expires, start again from the account settings.

## Email behavior and limits

Messages, read-state changes, moves and deletions are synchronized by mailbox.
Initial synchronization follows all pages; the page size is not a limit on the
number of messages imported. Interrupted runs retain committed progress, and
expired delta cursors trigger a full reconciliation. Message bodies and
attachment bytes are fetched when opened or downloaded.

Outgoing messages use MIME drafts and Microsoft's send operation, which stores
the sent copy in Sent Items. Bloomerp supports To/Cc/Bcc, plain and HTML bodies,
reply headers and file attachments. See Microsoft's
[MIME support](https://learn.microsoft.com/en-us/graph/outlook-send-mime-message)
and [send-draft behavior](https://learn.microsoft.com/en-us/graph/api/message-send?view=graph-rest-1.0).

The connector limits the complete base64-encoded MIME request to **4 MiB**.
This includes message headers, bodies and encoding overhead, so the total raw
attachment size must be smaller. This is a connector limit; it does not enable
Microsoft's large-attachment upload sessions. Microsoft describes that
separate mechanism in its [attachment upload documentation](https://learn.microsoft.com/en-us/graph/api/attachment-createuploadsession?view=graph-rest-1.0).
Incoming file attachments and attached messages can be downloaded. Cloud-linked
reference attachments are not downloaded by this connector.

"Accepted for sending" means Microsoft accepted the request for processing;
it does not confirm recipient delivery. Workflow actions use the same
`accepted` status and retain the message identifiers.

If Microsoft does not confirm a send, check Sent Items and Drafts before
sending again. The adapter does not automatically retry draft creation or send
requests after an uncertain response, because that could deliver duplicates.
The composer retains a pending reference and blocks another submission of the
same draft. Workflow email actions report an `unconfirmed` status. Calendar
email actions retain the message reference and block another send for the same
event until mailbox sync confirms delivery. Check the mailbox and sync the
account, then retry the same calendar action to finish its local update without
sending another copy. Keep Sent Items selected for synchronization so these
messages can be reconciled.

For developers extending this integration, see the provider-neutral
[email-provider contract](../developers/email-providers.md).
