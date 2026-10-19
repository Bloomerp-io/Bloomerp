# Conferencing foundation

Conferencing is an independent communication capability. Internal IM and future
calendar scheduling use its persistent rooms; each actual call has its own
session and temporary LiveKit room. Calendar RSVP responses must remain separate
from immediate call invitation responses.

## Configuration

`BloomerpConfig.conferencing` is a `ConferencingSettings` defined in
`bloomerp/config/definition.py`. Conferencing is disabled by default. Enabling it
requires `api_url`, `public_url`, `api_key`, and `api_secret`. The API URL uses
HTTP(S); the public URL uses WS(S). Use TLS for publicly reachable endpoints.
Secrets are excluded from configuration serialization and representations.

`configuration.get_conferencing_settings()` validates and snapshots the current
instance configuration. `livekit.LiveKitClient` passes it explicitly to the SDK;
it does not select credentials or addresses from the SDK's environment defaults.
An API request has a bounded timeout and closes its asynchronous HTTP client on
both success and failure.

Initially each customer instance runs its own LiveKit container on its existing
VM. The API address can point at the Docker service while browsers use a public
hostname. Moving that customer's LiveKit to a dedicated host changes configuration,
DNS, TLS and networking; it does not change model relationships or adapter APIs.
No cross-customer media service or credential sharing is required.

## Persistence

- `ConferenceRoom`: stable application identity, with optional IM context.
- `ConferenceSession`: one call; fresh provider room name, initial media mode,
  state and timestamps. Only one pending/ringing/active session per room.
- `ConferenceParticipant`: invitation response and display-name snapshot, separate
  from attendance. Nullable users preserve history; they do not grant guest access.
- `ConferenceAttendance`: actual connected intervals, with distinct device
  identities. Reconnects retaining the same provider SID reuse the interval.
- `ConferenceWebhookReceipt`: unique verified event ID and processing status.

These models are internal, do not generate APIs, and do not participate in global
search. Ordinary writes validate before persistence and freeze identifying
relations; bulk writes are deliberately unsupported. Deleting a conversation or
user clears its optional reference. Parent conference records with dependent
history are protected against deletion.

## Provider integration and endpoints

`IMProviderDefinition.calling` opts a provider into the generic IM call endpoint.
Its `IMCallingDefinition` declares current `IMCallCapabilities` (audio, video,
groups), eligible participants, a start handler, and an optional committed-state
projection hook. There are no internal-provider key checks in call dispatch.
Providers may return their own join/end URLs; adopting LiveKit is not mandatory.
The internal provider registers the reusable user-backed hooks in `im.py`.

- POST `components_im_start_call` with `conversation_id`, form fields `media_mode`
  (`audio`/`video`) and `client_id` (stable across retries).
- POST `components_conferencing_join` with `session_id` to accept and receive
  scoped browser credentials. Admission rechecks current source eligibility.
- POST `components_conferencing_end` with `session_id` to end for everyone as the
  host. Other participants leave through the media SDK; they cannot end the call.
- POST `conferencing_webhook` with the exact LiveKit body and Authorization header.
  Configure this endpoint in the per-instance LiveKit webhook settings.

Browser mutation endpoints require login and CSRF and return private, no-store
JSON. The webhook endpoint uses signature and body-hash verification instead of
browser sessions or CSRF. Start retries reuse the persisted session and provider
room name after uncertain network failures. End persists local closure before
media deletion; retrying completes cleanup without issuing new join tokens.

`conferencing.session.changed` notifications are published to invited user groups
after commit. The provider's optional hook projects call state into IM activity;
its declared timeline source renders session cards. Conversation fragments expose
the start URL and audio/video flags from effective provider capabilities.

Join tokens contain server-signed connection identities binding each device to
an invited participant. Attendance is created only after a verified connection
event. Duplicate events are deduplicated transactionally; a leave arriving before
a join remains closed. Full reconnections with the same identity but a new SID
produce separate attendance intervals.

Self-hosted LiveKit tokens already issued are not synchronously revoked by local
closure. Their short TTL limits new admission; callbacks for recreated closed
rooms trigger deletion. Callers must handle transport cleanup retries. Webhook
reconciliation is implemented; periodic reconciliation after lost callbacks is
still a subsequent operational task.

## Browser integration

The persistent `bloomerp:calling` component lives outside chat fragments and owns
one active call across both conferencing and carrier VoIP. Both use the common
IM start endpoint and capability-driven audio/video buttons. Conference records
and LiveKit media remain separate from PhoneCall records and carrier SDKs.

The phone IM provider declares audio-only capabilities and the `voip` browser
driver. Its start handler reserves a PhoneCall; its join endpoint rechecks actor
ownership and line access. Optional `cancel_url` releases an unused reservation.
Carrier calls expose no video or end-for-everyone capability. Hanging up remains
a transport operation, with final history reconciled through carrier webhooks.

`calling.registrations_resolver` declares authorized incoming accounts. The shared
registration endpoint adds the browser driver from the provider definition. The
"Enable incoming calls" action registers these accounts through the driver registry;
outgoing carrier calls also establish their required registration. Drivers deliver
incoming invitations through the common accept/dismiss contract. Carrier token
refresh and rejection remain inside the VoIP adapter. The UI never selects a
carrier SDK or assumes that a call has a ConferenceSession.

The persistent `bloomerp:calling` component lives outside chat fragments.
The IM provider declares `calling.browser_driver`; the built-in provider selects
`livekit`. The shipped TypeScript driver registry maps that name to the media
adapter. Chat UI never branches on a provider key or imports a media SDK.

Start responses carry `session_id`, `join_url`, `end_url`, and `media_mode`.
Join responses additionally carry `driver`, transport credentials (`url`, `token`),
`can_video`, and `can_end` (the capability flags are strings `true`/`false`).
Providers implementing another call backend supply compatible endpoints and a
bundled browser driver. The server remains authoritative for every action.

Audio/video buttons follow effective capabilities, including group support.
Invitations never open capture automatically. Joining enables microphone and,
for video calls, camera; permission failures leave controls available for retry.
Participants may leave locally; only hosts receive an end-for-everyone control.
Session cards allow joining after a page reload or missed notification. Incoming
notifications are delivered while the application's notification socket is open;
dismissal is local and is not recorded as an invitation rejection.

Run frontend interaction coverage with `npm run test:calling` from
`bloomerp/static_src`; `npm run build:js` rebuilds the browser bundle.
Instance deployment automation remains a subsequent task. Preserve a stable Bloomerp room/join URL for
future calendar invitations; never put a provider URL or expiring token in an
event. Scheduling a room must not provision an active media session.

### Call tab ownership

Starting or accepting a call keeps the original tab visible until its initial
microphone/camera requests have resolved or been rejected, then opens a presentation
tab. Browsers may block this delayed pop-up; the inline controls and **Open call**
button remain available for an explicit retry. The original application shell retains the transport, credentials, audio
playback, microphone and camera. Its compact controls include **Open call**;
closing the presentation tab never leaves or rejoins the call. The presentation
mirrors authorized controls and existing video streams, with muted video elements
to avoid duplicate audio. No provider keys or credentials are passed to the tab.

Leave and end-for-everyone remain distinct shared actions. Both close only the
acting user’s presentation tab, keeping their main Bloomerp tab open. Other
participants retain their presentation tabs with an ended status when the host
ends the call. Closing or refreshing
the original application disconnects local participation and closes its companion
view. When pop-ups are blocked, the owner displays the call inline and offers the
same Open call action to retry. LiveKit adaptive subscription visibility is
turned off because its owning video elements may be hidden while the presentation
tab displays the streams. Reopening a call view makes no additional join request.

Call presentation uses Django-translated markup and the owner's Bloomerp styles,
including the shared icon font. Transports can expose a normalized participant
roster independently of published video tracks, so camera-off participants retain
their tiles. LiveKit receives the IM provider's resolved display name, avatar and
initials in server-signed metadata after admission checks; participants cannot
rewrite that metadata. The UI replaces the avatar with the participant's active
camera stream and restores it when the camera is muted. Contact addresses and
credentials are not included in participant metadata.

Screen sharing is declared independently through `IMCallCapabilities.screen_share`
and returned as `can_screen_share` in authorized join credentials. Signed LiveKit
grants allow screen publication only when that capability is enabled. The shared
UI uses the optional transport `screenShare`/`screenSharing` contract; carrier
providers remain unsupported without UI branches. Sharing begins only from an
explicit click and a browser chooser, with video-only capture. Screen tiles use
contain scaling alongside camera/identity tiles. Native browser stop-sharing is
reflected in the controls. The original tab owns the call and publications; the tab whose Share screen
button is clicked invokes its own browser chooser directly and supplies the
selected stream through the shared transport contract. No focus transfer or
second click is required. Closing the call tab keeps the call, microphone and
camera connected; screen capture may end when its originating tab closes,
depending on the browser. Leaving or ending the call releases all media.

## Solo meetings and link admission

Bloomerp IM declares a `start_meeting` creation action. It reserves a standalone
room and invites only the current staff user; repeated start requests reuse the
same reservation. No empty IM conversation is created.

`IMCallCapabilities.share_links` enables the shared `share_url` control for
conference sessions. Hosts also receive `admissions_url`; carrier transports
without these capabilities expose neither control. Links address a public model
view for `ConferenceSession` and are random per occurrence. Ended, cancelled and
failed meetings show a styled terminal notice without lobby controls or media
credentials. Unknown links, archived rooms and sources that no longer permit
sharing still return 404. Admission and credential endpoints remain live-only.
Existing sessions receive unique tokens during migration 0097.

`ConferenceAdmission` stores a pending, admitted or rejected visitor separately
from IM membership. An authenticated account supplies its identity; an anonymous
visitor supplies only a display name. Both wait for the host. A private browser
session binding plus the host decision is required to issue media credentials.
The public view never returns conversation history, the waiting list, other
guests' identities, or a media token before admission. Host decisions and guest
join tokens recheck session state; CSRF protects mutations. Admitted guests are
recognized by webhook reconciliation without granting access to the source IM.

The host's call controls poll for waiting names and offer Admit/Decline. Guests
poll only their own status and explicitly click Join after admission. Closing
the guest call presentation keeps its original lobby tab's transport alive.
The room capacity comes from `ConferencingSettings.max_participants` (32 by
default, with room for pre-existing invitees). Sharing uses the current site
origin, so external guests need a publicly reachable Bloomerp and LiveKit URL.
