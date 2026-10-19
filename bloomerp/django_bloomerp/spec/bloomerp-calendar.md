# BloomERP calendar

The BloomERP calendar will be a unified calendar.


## Core requirements

- As a user, I need to be able to see the calendars for other users I have access to.
- I need to be able to add objects to a calendar
- I need to be able to easily import items from an email attachment into a calendar
- There needs to be a button on the inbox to show the calendar
- I need to be able to easily send calendar invites to foreign email addresses, as well as internal users
- I need to be able to create a calendar link for external people to schedule meetings, like calendly

## Proposed ERD

The Inbox is the local calendar owning unit; a calendar is a view of events, with
no separate Calendar model. CalendarEvent and Inbox have an explicit many-to-many
relationship for placement: one shared event can appear in several Inbox calendars,
and each Inbox can display many events. Placement is WHERE an event appears,
participants are WHO attends with independent responses, and organizer identity
is WHO manages scheduling invitations. These are separate relationships.

```mermaid
erDiagram
    Inbox }o--o{ CalendarEvent : displays
    Inbox |o--o{ CalendarEvent : organizes_locally
    CalendarEvent ||--o{ CalendarEventParticipant : has
    User |o--o{ CalendarEventParticipant : identifies
    Inbox }o--o{ CalendarBooking : booking_destinations
    Inbox ||--o{ CalendarBooking : organizes_bookings
    CalendarBooking ||--o{ CalendarBookingSubmission : receives
    CalendarBookingSubmission |o--o| CalendarEvent : originates

    Inbox {
        uuid id PK
    }

    User {
        uuid id PK
    }

    CalendarEvent {
        uuid id PK
        uuid calendar_booking_submission_id FK, UK "nullable one-to-one"
        uuid organizing_inbox_id FK "nullable for external organizer"
        string organizer_email
        string title
        string content
        string location
        datetime start "nullable UTC instant for timed events"
        datetime end "nullable UTC instant for timed events"
        string event_timezone "nullable IANA zone for timed events"
        date start_date "nullable for timed events"
        date end_date "nullable exclusive end for all-day events"
        bool all_day
    }

    CalendarEventParticipant {
        uuid id PK
        uuid event_id FK
        uuid user_id FK "nullable"
        string email "nullable for internal participants"
        string display_name "nullable"
        string response_status "awaiting response, accepted, tentative, declined"
        datetime responded_at "nullable"
    }

    CalendarBooking {
        uuid id PK
        uuid organizing_inbox_id FK
        string title
        text description
        int meeting_duration_minutes
        json availability_hours
        string timezone "IANA zone"
        string public_token UK "unguessable"
        bool active
    }

    CalendarBookingSubmission {
        uuid id PK
        uuid calendar_booking_id FK
        string name
        string email
        datetime submitted_at
    }
```

- Event placement uses the explicit Inbox many-to-many relation, not a single
  placement foreign key. Adding or moving a placement changes that relation
  without duplicating the event or changing its participants or organizer.
- Locally organized events have one `organizing_inbox_id`, and `organizer_email`
  records its sending identity. Externally organized events have a null
  `organizing_inbox_id` and the external organizer email. An Inbox placement does
  not make that Inbox an organizer or grant authority over an external meeting.
- Placing an event in a shared team Inbox does not make every user with access
  an attendee. Participants and their response statuses are recorded explicitly.
- Each participant belongs to exactly one event. Internal participant identity is
  a User, not an Inbox; the user link is optional for external participants.
- External participants require an email address. Internal participants require a
  user link and may also record the email address used for the invitation.
  A participant must therefore have at least a user link or an email address.
- An internal participant relation records attendance. Calendar placement comes
  from the explicit Inbox many-to-many relation, not from participant relations
  alone. Attendees share one event rather than receiving duplicate events.
- A participant can respond in the app or by calendar email. Both channels update
  the same participant's response status and response timestamp without creating
  another attendee. `responded_at` is nullable until a response is received.
- The referencing framework attaches contacts and other business objects as
  context, separately from participant identity.
- Event access can be separate from email access. Visibility based on user access
  is under consideration; the exact authorization policy remains unresolved.


### Placement examples

- An internal meeting has explicit user participants and the same event placed
  in the attendees' Inbox calendars.
- A customer meeting can appear in both the salesperson's Inbox and the shared
  sales Inbox. Shared sales Inbox access alone does not make colleagues attendees.
- Adding or moving an event to another Inbox changes placement only. A change to
  the shared meeting's time updates the same event in every destination calendar,
  subject to the organizer's scheduling authority.

## Timezones

- Timed events require timezone-aware `start` and `end` instants normalized to UTC,
  with `end` after `start`, plus an IANA `event_timezone` such as
  `Europe/Brussels`. Their date-only fields are null. Viewers see instants converted
  to their own timezone.
- All-day events require `start_date` and an exclusive `end_date` after it.
  `start`, `end`, and `event_timezone` are null. Display these as calendar dates,
  not midnight UTC instants that shift dates when converted for other viewers.
- Booking availability hours are interpreted in the CalendarBooking's IANA timezone,
  including daylight saving changes. Do not offer nonexistent local times. When
  a local time is ambiguous, require an explicit occurrence or UTC offset before
  scheduling rather than silently guessing.
- Imported calendar data should preserve source timezone semantics and definitions
  where feasible. A source TZID may be custom rather than IANA. Resolve it using
  its supplied definition or a verified mapping before normalizing timed instants
  and selecting an IANA event timezone. If it cannot be resolved, retain the source
  for review instead of guessing a timezone. Preserve date-only imports as all-day
  date ranges.

## Calendar booking

- A CalendarBooking provides a public shareable booking page with many-to-many
  target Inboxes as destinations. These are all placement
  destinations, not a round-robin pool from which one salesperson is chosen.
  A separate organizing Inbox defines the sending identity. Its duration,
  availability hours, timezone, title, description, public unguessable token,
  and active flag define the reusable configuration.
  An active booking must have destination Inboxes and an organizing Inbox.
  CalendarBookingSubmission records booking origin and visitor details, provides
  a place for future booking-form answers, and belongs to
  CalendarBooking. CalendarEvent optionally references its originating submission
  through the nullable unique `calendar_booking_submission_id` foreign key
  (one-to-one). Each event has zero or one submission, and each submission has at
  most one event. Ordinary events leave the reference null, and submissions have
  no foreign key to events. A successful MVP booking creates exactly one shared
  event atomically with its submission, placements, and participants. No separate
  Calendar model is needed. The event remains the source of truth for the selected
  meeting time.
- The public page exposes free slots, not private event details. Calculate slots
  from configured availability and the busy calendars selected to constrain booking,
  and display them in the visitor's own timezone. An inactive link cannot accept bookings.
- The visitor selects a slot and supplies their name and email. Submission
  atomically rechecks link activity and availability while reserving the time, so
  concurrent conflicting bookings cannot both succeed. A conflict asks the visitor
  to choose another available slot without creating a successful submission, event,
  or participants.
- A successful MVP booking creates ONE shared CalendarEvent and places it in all
  configured destination Inboxes, using the separately specified organizing Inbox.
  Save the event, all destination placements, the visitor participant, any explicitly
  configured actual attendees, and CalendarBookingSubmission together in the same
  atomic confirmation. The
  submission records name, email, and `submitted_at` and references CalendarBooking.
  Set the new event's `calendar_booking_submission_id` to that submission in the
  same atomic operation, without a direct configuration foreign key on the event.
  One meeting has one shared event record across internal attendees, with
  participant records rather than clones per Inbox or submission. Booking confirms
  the visitor's participation: their status is accepted with `responded_at` set to
  the booking confirmation time. Their supplied name is recorded as their participant
  display name. Other attendees retain independent response statuses.
- Selecting actual attending users and whose busy calendars constrain slots remain
  unresolved. Do not infer attendees or busy-calendar selection from destination
  Inbox sharing, ownership, or access. The organizing Inbox supplies scheduling
  identity, not an implicit singular host.
- Confirm the booking immediately and send a standard calendar scheduling invitation
  through the organizing Inbox. The visitor remains accepted without responding to that
  email. The MVP requires no approval step and includes no payments or round-robin
  routing.

### Booking sequence

```mermaid
sequenceDiagram
    actor Visitor
    participant Page as Public booking page
    participant Bloomerp
    participant Inbox as Organizing Inbox

    Visitor->>Page: Open active booking link
    Page->>Bloomerp: Request available slots
    Bloomerp-->>Page: Return free slots without private event details
    Page-->>Visitor: Display slots in visitor timezone
    Visitor->>Page: Select slot and submit name and email
    Page->>Bloomerp: Book selected instant
    Bloomerp->>Bloomerp: Atomically recheck active link and conflicting reservations
    alt Link inactive or slot conflicts
        Bloomerp-->>Page: Reject without creating submission, event, or participants
        Page-->>Visitor: Show unavailable result and refresh slots
    else Slot remains available
        Bloomerp->>Bloomerp: Atomically reserve time and save submission, one shared event, all destination placements, and visitor plus explicitly configured actual attendees
        Note over Bloomerp: Visitor is accepted immediately<br/>All destination calendars display the same event with optional one-to-one submission reference
        Bloomerp-->>Page: Confirm booking immediately
        Page-->>Visitor: Show confirmed meeting in visitor timezone
        Bloomerp->>Inbox: Send standard calendar scheduling invitation
        Inbox-->>Visitor: Deliver invitation for confirmed booking
    end
```

- For the booking link, use a view detail view

## Sequence

### Outgoing invitation

Proposed external invitation and response flow through the organizing Inbox:

```mermaid
sequenceDiagram
    actor Organizer
    participant Bloomerp
    participant Inbox as Organizing Inbox
    participant App as Recipient calendar app
    actor Recipient
    participant Sync as Bloomerp email sync

    Organizer->>Bloomerp: Schedule meeting from a contact
    Bloomerp->>Bloomerp: Save one event with organizer identity and explicit Inbox placements
    Bloomerp->>Bloomerp: Save participant with invited email and awaiting response
    Bloomerp->>Bloomerp: Generate standard iCalendar scheduling invitation
    Bloomerp->>Inbox: Send invitation using Inbox email identity
    Inbox->>App: Deliver scheduling invitation
    App->>Recipient: Display invitation
    Recipient->>App: Accept, tentatively accept, or decline
    App->>App: Update recipient's own calendar
    alt Recipient chooses to send a response
        App->>Inbox: Send structured calendar reply
        Inbox->>Sync: Receive reply through email sync
        Sync->>Sync: Detect and parse calendar reply
        Sync->>Bloomerp: Match stable event calendar UID and participant invited email
        Bloomerp->>Bloomerp: Validate applicable organizer and event revision context
        alt Reply matches and context is valid
            Bloomerp->>Bloomerp: Update same participant response_status and responded_at
            Organizer->>Bloomerp: View attendance
            Bloomerp-->>Organizer: Show updated response
        else Reply is unmatched or context is invalid
            Bloomerp->>Bloomerp: Leave attendance unchanged for review
        end
    else Recipient does not send a response
        Note over App,Bloomerp: Recipient's local calendar changes<br/>Bloomerp remains awaiting response
    end
```

- This is a scheduling invitation, not merely an ordinary ICS attachment;
  exporting ICS alone does not guarantee native response controls in the recipient's app.
- Processing incoming replies through email sync is required in addition to
  exporting and sending the invitation.
- Unmatched replies must not silently update another event's attendance. Repeated
  processing of the same reply must not create duplicate participants or events.

### Incoming invitation

An external organizer can invite an email address linked to a Bloomerp Inbox.
Email sync automatically adds the receiving Inbox as a placement of the pending
shared event, without requiring a manual ICS import or replacing other placements.

```mermaid
sequenceDiagram
    actor External as External organizer
    participant Inbox as Receiving Inbox
    participant Sync as Bloomerp email sync
    participant Bloomerp
    actor User as Inbox user

    External->>Inbox: Send calendar scheduling invitation to linked email address
    Inbox->>Sync: Sync incoming email
    Sync->>Sync: Detect and parse calendar MIME scheduling content
    Sync->>Bloomerp: Match meeting UID and organizer identity with revision context
    alt New valid invitation
        Bloomerp->>Bloomerp: Save shared event with external organizer identity and receiving Inbox placement
        Bloomerp->>Bloomerp: Save invited participant as awaiting response
    else Valid update or cancellation for existing meeting
        Bloomerp->>Bloomerp: Reuse same meeting and add receiving Inbox placement if needed
        Bloomerp->>Bloomerp: Apply applicable revision across all placements
    else Unmatched cancellation or invalid context
        Bloomerp->>Bloomerp: Leave calendar unchanged for review
    end
    opt Current valid invitation remains actionable
        Bloomerp-->>User: Show pending invitation with Accept, Tentative, Decline
        Note over Bloomerp,User: Calendar placement alone does not mean accepted
        User->>Bloomerp: Accept, tentatively accept, or decline
        Bloomerp->>Bloomerp: Update same participant response_status and responded_at
        Bloomerp->>Inbox: Send standard iTIP reply using invited Inbox email identity
        Inbox->>External: Deliver response for same meeting identity and invitation revision
    end
```

- Detect scheduling content from calendar MIME parts and scheduling metadata,
  rather than relying only on attachment file names. Ordinary calendar file
  imports remain a fallback.
- Repeated email sync must reuse the same event and invited participant, without
  duplicates. Match updates and cancellations against the existing meeting UID
  and organizer identity, validate their context, and apply the relevant revision
  rather than creating copies. Stale or repeated messages must not roll back newer
  meeting state.
- The receiving email identifies the invited participant. A User link may
  be recorded when known, but the Inbox itself is not a User. No user
  default-Inbox routing policy is defined by this proposal.
- A local organizer changes the time by sending a scheduling update with the same
  meeting identity and a newer revision. Updates from an external organizer sync
  into the existing event. An attendee editing their local calendar placement
  cannot reschedule the meeting for everyone.

## Code

```python
class CalendarEvent:
    ...

    def to_invite(self):
        """To ICS/ICALL, ..."""
        pass

```


