# Mention notifications

Object-reference reconciliation publishes `mentions.created` for newly introduced
recipient/field scopes. Manual mentions use the object scope; inline mentions use
their `ApplicationField`. Repeated occurrences in a field produce one inbox item.
Re-saving an existing scope, including with regenerated editor occurrence IDs,
does not notify again. Removing a mention leaves the inbox history intact;
removing and later reintroducing it is a new mention.

The comparison runs under the existing parent-row lock, inside the same
transaction as reference reconciliation and inbox-item creation. Saves with no
new scopes perform no notification-folder lookup or delivery. New scopes share
one field-metadata lookup and one recipient-folder query.

Notifications use the built-in inbox system and target recipient-owned
notification folders, not other owners' inboxes merely shared with a recipient.
Existing explicit sharing of a recipient-owned inbox still applies. No email or
other outbound channel is involved. Staff inboxes are provisioned through the
existing staff-user preference lifecycle.

Snapshots contain the actor label, source object label, optional field label and
navigation URL. They do not copy field values or comment content. Object display
labels remain visible in the inbox even if the recipient lacks target access;
following the URL uses the ordinary detail-view permissions. Comments use the
existing permission-checked redirect to the parent object's Comments sidebar and
comment anchor. Deleted source objects do not prevent rendering the snapshot.

Mention sources opt into `defer_notifications_until_commit` and
`plain_text_notifications` on `InboxSourceExecutionResult`. Inbox writes remain
atomic, while realtime delivery is a robust post-commit callback. The HTML-capable
toast boundary escapes plain-text snapshots; inbox templates also escape them.
These options preserve the existing behavior of other notification sources.
