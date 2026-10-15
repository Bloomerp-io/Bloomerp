# VoIP and phone conversations

The built-in Phone IM provider uses a separate `VoIPConnection` and `VoIPNumber`. Staff remains a separate internal provider. Neither requires an `IMConnection`. Each conversation stores its provider explicitly; a phone conversation belongs to one business line and one normalized remote number.

## Configure Twilio

1. Configure `BLOOMERP_CONFIG.email_secret_key`, the existing communications encryption key. Retain this key across deployments so saved credentials remain readable.
2. Apply migrations and build the frontend after installing Python and npm dependencies.
3. Open **Communication → Create a VoIP connection**, choose **Twilio**, and enter the account SID, auth token, and public HTTPS base URL of this instance.
4. For browser calls, also supply a Twilio API key SID, API key secret, and TwiML application SID belonging to that account.
5. Creation returns directly to the connection object. Run its **Synchronize phone numbers** object action. This validates credentials, imports owned numbers and capabilities, and imports the last 30 days of call history initially. Later synchronization uses a one-day overlap from the previous successful run. Existing local labels and staff assignments are retained; missing carrier numbers become inactive.
6. Open **Communication → Phone numbers** and assign each number to the staff who may use it. New imported lines are assigned to the staff member performing the synchronization.
7. Open the connection’s **Reconfigure connection** action to see its callback URLs. For existing numbers, copy these into Twilio: use the Voice URL for both the TwiML application's Voice request and each number's incoming Voice request; use the SMS URL for each number's incoming Messaging request. Use HTTP POST. Configure the displayed call-status URL for incoming call status notifications. Outgoing SMS status and dial-leg callbacks are supplied by Bloomerp automatically.
8. Staff select **Enable incoming calls** in the messaging panel to register for incoming calls. Browser calling requires microphone permission and a secure browser context. Selecting a phone recipient then chooses an accessible business number when more than one is available.

Synchronization is an object action dispatched through `run_async_or_sync`: it queues an importable job when a worker is available and otherwise runs inline. The worker reloads the actor and checks connection change permission again. History remains stored when a line is disabled. Calls that cannot be associated with an imported line remain in account history, outside line-scoped chat access. Carrier history is reconciled into an existing matching phone conversation; inbound messages and calls can create a conversation directly.

## Configure Telnyx

This integration supports browser audio calls and webhook-driven call history.
It imports numbers purchased in the Telnyx dashboard. It does not advertise SMS,
video, number purchasing, or historical call import. Calls use the same Phone IM
provider, calling capabilities, `PhoneCall` records and shared `bloomerp:calling`
controls as Twilio; no Telnyx cases belong in chat templates or the UI controller.

1. In Telnyx, create a **TeXML application** dedicated to this Bloomerp instance.
   Activate it and assign an outbound voice profile permitting your intended
   telephone destinations. Set an inbound SIP subdomain (for example
   `my-bloomerp`) with receive settings **Only my connections**.
2. Create a separate **Credentials SIP connection** for browser registrations.
   Activate it, set SIP URI calling to **Internal**, and leave its outbound voice
   profile unassigned. Do not attach purchased numbers to this browser connection.
   Bloomerp checks this restriction before issuing browser credentials: telephone
   destinations must be selected by the application's authorized TeXML handler.
3. Buy and activate your number in the dashboard, then assign it to the TeXML
   application. Numbers attached to other applications are excluded from sync.
4. Create a Bloomerp VoIP connection with provider **Telnyx**. Enter the Telnyx
   account ID (the `AccountSid`/user ID in TeXML callbacks), API v2 key, Ed25519
   webhook public key, TeXML application ID, browser credential connection ID,
   SIP subdomain (without `.sip.telnyx.com`), and this instance's public HTTPS URL.
   The API key uses the existing encrypted communications credential storage.
5. Open **Reconfigure connection** to obtain its callback URLs. Configure the
   TeXML application's Voice URL and status callback to those addresses, using
   POST. Bloomerp verifies the timestamp, Ed25519 signature over the exact request
   bytes, account ID and application ConnectionId before interpreting a callback.
6. Run **Synchronize phone numbers** and assign staff to the imported line.
   Synchronization preserves local labels and assignments; new numbers are
   assigned to the staff member performing the sync.
7. Refresh the rebuilt application and choose **Enable incoming calls** in the
   messaging panel. Start an outgoing audio call from a phone conversation, or
   call your purchased number from another phone and explicitly accept it.

Use HTTPS with publicly reachable callbacks during local testing, for example
through your existing development tunnel. `localhost` is not reachable by Telnyx.
The browser also needs a secure context and microphone access. Account funding,
number activation and allowed destinations are managed in Telnyx.

The adapter creates named, expiring telephony credentials per instance/user and
renews them while the browser remains registered. The browser receives only a
JWT and application SIP domain. Outgoing call references are signed, short-lived
reservations; the TeXML callback rechecks current line access and reads caller
and destination numbers from the stored PhoneCall. Duplicate CallSid delivery
reuses that record, while a different CallSid cannot reuse a submitted reservation.
Incoming routing resolves only credentials of currently assigned active staff.
Existing calls and already-issued credentials are not synchronously revoked by
an assignment change; new routing and token renewal recheck authorization.

Call status notifications use the common reconciliation logic. Individual failed
parallel dial legs do not end the root call; the Dial action supplies the aggregate
outcome. The integration relies on status callbacks for history and does not
backfill calls that happened before configuration or recover lost callbacks.

Run `npm run test:calling` and `npm run build:js` in `bloomerp/static_src`.
The automated tests use mocked carrier transport; real account routing, audio,
and dashboard settings require a live smoke test after setup.

References: [Telnyx application setup](https://support.telnyx.com/en/articles/4374050-configuring-call-control-texml-applications-voice-api),
[TeXML Dial](https://developers.telnyx.com/docs/voice/programmable-voice/texml-verbs/dial),
[TeXML callbacks](https://developers.telnyx.com/api-reference/callbacks/texml-call-initiated),
[Telnyx API schema](https://raw.githubusercontent.com/team-telnyx/openapi/master/openapi/spec3.json).

## Provision and reconfigure from Bloomerp

Use **Create phone number** on an active connection. Search by country code, number type (local/mobile/toll-free), and an optional number pattern. Select an available number, provide an optional label and any required Twilio address/bundle identifiers, and confirm the applicable carrier charges. The selection is signed for the account and actor and expires after 15 minutes. Bloomerp provisions the exact number, installs its Voice/SMS/status callbacks, stores the carrier identity and capabilities, and assigns the current user. Repeating the request reuses the same local or already-owned carrier number.

Twilio handles availability and regulatory requirements. See the [IncomingPhoneNumber API](https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource) for supported address and bundle references. Provisioning does not silently purchase a different number when the selected one is unavailable.

Use **Reconfigure connection** to edit provider settings or rotate credentials. Blank secret inputs preserve encrypted stored values; provider and account identity stay fixed. Saving returns to the connection object and marks it draft until the synchronization action validates the new configuration. Credentials and raw settings are excluded from the configured default dataview and detail layout.

## Provider extension points

`VoIPProviderDefinition` owns carrier configuration and number controls. Set `number_search_schema` and `number_purchase_schema` to `VoIPNumberOptions` subclasses; their Pydantic fields supply labels, help, types and validation through the existing schema form mapper. Use `field_choices` for translated choice labels. Shared forms retain only the signed offer, local label and explicit purchase consent; carrier options are normalized before reaching the adapter. A provider without both schemas cannot open number provisioning.

The definition also supplies purchase notice/pricing, configuration and callback help, account identity and immutable fields, callback labels, expected transport exceptions, SMS length limit, webhook handlers and browser driver. `account_id_field` is restored from the saved external account ID during reconfiguration; blank secrets retain encrypted values. Carrier adapters resolve callback URLs from their own configuration. Shared controllers do not require Twilio's public URL field or regulatory references.

`max_assigned_users` optionally limits a line's staff assignments. It defaults to
`None` (no limit); Twilio declares `10` to match its simultaneous browser dial
limit. M2M additions enforce the configured limit for detail forms, assignment
components and reverse user relations. This validation does not reconcile
conversation membership or inbox rows.

IM definitions accept typed callables or dotted import paths for selection,
creation, permission, start, send, action, identity-label and timeline hooks.
The callable aliases and `IMSendHandler` protocol in the IM definition document
the required arguments and return values. `resolve_hook` supports either form;
import paths are resolved lazily to avoid circular imports.

Callback routes require the selected adapter to authenticate the request before dispatching to provider-owned protocol handlers. The default adapter rejects requests. Twilio handlers live under `communication/builtins/voip/builtins/twilio_webhooks/` and retain exact-URL signature and account checks. Browser token responses select a driver declared by the provider; `static_src/ts/communication/voip/` holds the neutral device/session contract and shipped driver registry. Twilio SDK state, events and outgoing parameters stay inside its driver; the shared Calling component owns the UI lifecycle. Unsupported drivers fail closed.

`IMProviderDefinition.creation_actions` declares provider-owned creation flows. Each `IMCreationAction` supplies a stable key, translated label, icon, importable handler and permission resolver. The recipient picker renders authorized actions beneath that provider's heading using the shared dropdown submenu. The shared creation endpoint requires explicit provider/action values and repeats authorization for GET and POST; an undeclared action is rejected. Bloomerp declares staff-group creation; Phone, WhatsApp and Slack currently declare none.

`IMProviderDefinition.selection_steps` declares ordered selection steps. Each resolver receives the actor, validated preceding selections, a search term, and an optional selected value. It returns `IMSelectionPage`; the framework revalidates every submitted selection. `start_handler`, `send_handler`, `actions_resolver`, `identity_label_resolver`, and `timeline_sources` own provider-specific behavior while sharing the picker and conversation UI. Draft Slack/WhatsApp adapters retain their unavailable transport status.

The Phone directory discovers registered `PhoneNumberField` fields, applies row and phone-field visibility, and uses each accessible object's string representation as its label. Signed selections are rechecked against the original record and field. `IMIdentity` holds the stable normalized phone identity; `IMIdentitySource` stores separate record/field associations. Labels are resolved per viewer so shared-line membership does not disclose inaccessible records.

`PhoneCall` and `PhoneCallEvent` retain carrier state independently. `IMConversationActivity` projects calls into inbox previews and read state, while the provider's timeline renderer shows the call records alongside messages. Root calls are shown once; carrier child legs remain available for reconciliation.

## Access and delivery behavior

`communication/builtins/voip/access.py` owns account and line access. Connection administration requires standard global and row-level change permission; being the creator is insufficient. Creation requires the standard model add permission. Reconfiguration additionally checks change permission for name, settings and credentials. Line assignments authorize usage, and every send, token request and call checks current access. Historical conversation membership alone does not grant use of a revoked number. Tokens last ten minutes; carrier callbacks require a valid Twilio signature against the configured public URL and matching account SID.

SMS sends persist a client request identifier before transport dispatch. Repeating that request does not send twice. A network timeout leaves delivery pending because Twilio may have accepted it; a signed delivery callback can resolve the status. Call events are deduplicated, and late nonterminal callbacks cannot overwrite terminal outcomes.

The automated suite uses generated Bloomerp cases, real signature/JWT validation, mocked carrier transport and browser journeys for creation, provisioning, reconfiguration and phone selection. A live account, publicly reachable callbacks, actual SMS delivery and microphone/audio routing still require deployment verification.
