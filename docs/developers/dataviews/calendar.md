# Calendar color grouping

`CalendarDataView.color_grouping_field` accepts a readable scalar field, a
single relation, or a relation with multiple values. For example:

```python
CalendarDataView(
    name="Planning",
    start_field="start",
    end_field="end",
    color_grouping_field="teams",
)
```

The calendar renders each record once. For a multi-value relation it uses one
membership as the event color and shows the remaining memberships as colored
dots. The legend uses the same colors. Relation colors are derived from stable
object IDs, so renaming a group, filtering, and loading another calendar page
do not change its color. The palette repeats after its available colors are
exhausted.

The renderer checks access to the grouping field on each record and scopes
related labels through the related model's read policy. Preference relations
use the existing preference ownership and sharing rules. Multi-value relations
are prefetched to avoid querying memberships separately for every event.

An embedding page can send these optional presentation parameters:

| Parameter | Meaning |
| --- | --- |
| `calendar_color_field` | Override the grouping field using another readable field name. |
| `calendar_color_values` | Comma-separated membership IDs to include in colors, dots, and the legend. |
| `calendar_color_preferred` | Prefer this membership ID as the primary event color when present. |

These parameters affect presentation only. They neither filter records nor
grant access. Apply the normal structured row filter separately, for example
an `inboxes` / `values_in` condition with a list of IDs to select the union of
several Inbox calendars. Existing row and field permissions still apply.

The Inbox-specific dropdown lives in
`templates/models/calendar_event/align_calendars.html` and
`static_src/ts/components/inbox/InboxCalendarOverlay.ts`. Its component endpoint saves the preference and reloads the ordinary dataview
loader with an Inbox membership filter. The generic calendar renderer has no
dependency on the Inbox model. A related model may provide
`get_calendar_group_queryset(user)` to resolve its own scoped grouping authority.

The event form includes a separate `calendar-availability` component with its
own template and endpoint. The editor passes participant IDs, date, timezone,
and the current selection through `setSelection()`. The sidebar emits
`bloomerp:availability-time-selected` with the chosen range; only the event
editor updates form fields. No availability action is attached to the create
view, and neither component changes shared modal padding.
