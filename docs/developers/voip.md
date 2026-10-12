# VoIP and phone conversations

The built-in Phone IM provider uses a separate `VoIPConnection` and `VoIPNumber`. Staff remains a separate internal provider. Neither requires an `IMConnection`. Each conversation stores its provider explicitly; a phone conversation belongs to one business line and one normalized remote number.

## Configure Twilio

1. Configure `BLOOMERP_CONFIG.email_secret_key`, the existing communications encryption key. Retain this key across deployments so saved credentials remain readable.
2. Apply migrations and build the frontend after installing Python and npm dependencies.
3. Open **Communication → Create a VoIP connection**, choose **Twilio**, and enter the account SID, auth token, and public HTTPS base URL of this instance.
4. For browser calls, also supply a Twilio API key SID, API key secret, and TwiML application SID belonging to that account.
5. Select **Validate and synchronize**. This validates credentials, imports owned numbers and capabilities, and imports the last 30 days of call history initially. Later synchronization uses a one-day overlap from the previous successful run. Existing local labels and staff assignments are retained; missing carrier numbers become inactive.
6. Under **Manage VoIP connections**, assign each number to the staff who may use it. New imported lines are assigned to the staff member performing the synchronization.
7. Copy the displayed callback URLs into Twilio: use the Voice URL for both the TwiML application's Voice request and each number's incoming Voice request; use the SMS URL for each number's incoming Messaging request. Use HTTP POST. Configure the displayed call-status URL for incoming call status notifications. Outgoing SMS status and dial-leg callbacks are supplied by Bloomerp automatically.
8. Staff select **Enable phone** in the messaging panel to register for incoming calls. Browser calling requires microphone permission and a secure browser context. Selecting a phone recipient then chooses an accessible business number when more than one is available.

Synchronization is currently an explicit action on the management page. History remains stored when a line is disabled. Calls that cannot be associated with an imported line remain in account history, outside line-scoped chat access. Carrier history is reconciled into an existing matching phone conversation; inbound messages and calls can create a conversation directly.

## Provider extension points

`IMProviderDefinition.selection_steps` declares ordered selection steps. Each resolver receives the actor, validated preceding selections, a search term, and an optional selected value. It returns `IMSelectionPage`; the framework revalidates every submitted selection. `start_handler`, `send_handler`, `actions_resolver`, `identity_label_resolver`, and `timeline_sources` own provider-specific behavior while sharing the picker and conversation UI. Draft Slack/WhatsApp adapters retain their unavailable transport status.

The Phone directory discovers registered `PhoneNumberField` fields, applies row and phone-field visibility, and uses each accessible object's string representation as its label. Signed selections are rechecked against the original record and field. `IMIdentity` holds the stable normalized phone identity; `IMIdentitySource` stores separate record/field associations. Labels are resolved per viewer so shared-line membership does not disclose inaccessible records.

`PhoneCall` and `PhoneCallEvent` retain carrier state independently. `IMConversationActivity` projects calls into inbox previews and read state, while the provider's timeline renderer shows the call records alongside messages. Root calls are shown once; carrier child legs remain available for reconciliation.

## Access and delivery behavior

`communication/builtins/voip/access.py` owns account and line access. Active staff manage their own connections; superusers manage all. Line assignments authorize usage, and every send, token request and call checks current access. Historical conversation membership alone does not grant use of a revoked number. Tokens last ten minutes; carrier callbacks require a valid Twilio signature against the configured public URL and matching account SID.

SMS sends persist a client request identifier before transport dispatch. Repeating that request does not send twice. A network timeout leaves delivery pending because Twilio may have accepted it; a signed delivery callback can resolve the status. Call events are deduplicated, and late nonterminal callbacks cannot overwrite terminal outcomes.

The automated suite uses generated Bloomerp cases, real signature/JWT validation, mocked carrier transport and browser journeys. A live account, publicly reachable callbacks, actual SMS delivery and microphone/audio routing still require deployment verification.
