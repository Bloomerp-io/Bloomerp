# Kanban grouping and colours

`KanbanDataView` supports named lanes containing multiple values of the grouping
field. Map lane names to lists of the field's serialized values:

```python
from bloomerp.dataviews.kanban.config import KanbanDataView

view = KanbanDataView(
    group_by_field="status",
    custom_groupings={
        "Applied": ["applied_via_website", "applied_via_email"],
        "Selected": ["candidate_informed_via_email", "candidate_informed_via_phone"],
    },
    lane_colouring={"Applied": "#2563eb", "Selected": "#16a34a"},
)
```

Each field value may belong to only one custom lane. Unmapped values retain
individual lanes. Empty choice destinations remain available; related-object
destinations use the existing permission and `limit_choices_to` filters.
Related-object and numeric values are represented by their string values.
`__none__` represents an unassigned value when that lane exists.

Colours use six-digit hex values. With custom groups, colour keys are the custom
lane names. Otherwise they are the original field values (including related
object IDs). Colours for removed or unavailable lanes are ignored, and can be
removed or reused in the display options. Pagination and sorting apply to the
combined lane queryset.

Lane metadata is collected separately from card objects. The mapping editors
reuse one metadata result per dataview state, and custom lanes are combined
before their card pages are loaded. A lazy-loading request filters to its
requested ordinary or custom lane and loads only that lane's page.

In display options, select the grouping field first, then add named custom
mappings and click **Apply**. The colour editor lists the resulting
lanes after the grouping is saved. During dragging, each lane is divided into
equal-height sections for its individual categories. Dropping onto a section
uses its concrete field value, including within the card's current lane.
Alt+Left/Right starts a keyboard move. Left/Right selects a lane, Up/Down selects
a category, Enter confirms, and Escape cancels. Category sections are hidden
when movement ends.

Card headers use the original category's configured colour, falling back to
the custom lane colour. Header text automatically uses contrasting black or
white. Category sections show a tint of the same colour during movement.

The display options field chips list visible fields in their displayed order,
followed by hidden accessible fields. Drag a visible chip's handle to reorder
the card fields. The order is saved for the current view type; other views keep
their own order. Clicking a chip still toggles its visibility.

## Reusable mapping field

`MappingField` returns a dictionary with string keys and values cleaned by a
configured Django field. It accepts optional `left` and `right` choice lists,
`left_field` and `right_field` for typed validation, `left_widget` and
`right_widget` for presentation overrides, and `allow_adding_groups`.

```python
from django import forms
from bloomerp.form_fields.mapping_field import MappingField

class AssignmentForm(forms.Form):
    assignments = MappingField(
        right_field=forms.MultipleChoiceField(
            choices=[("web", "Website"), ("email", "Email")],
        ),
        required=False,
    )

class LimitsForm(forms.Form):
    limits = MappingField(
        left=[("daily", "Daily"), ("weekly", "Weekly")],
        right_field=forms.IntegerField(min_value=0),
        required=False,
    )
```

Providing `left` defaults to fixed rows; omitting it defaults to editable rows
with add/remove controls. Blank fixed rows are omitted from the result.
Duplicate cleaned keys and incomplete editable rows raise validation errors.
The widget delegates rendering and submitted-value extraction to the child
widgets, including multiple selections. Dictionaries and JSON strings are
accepted as input alongside the indexed rows posted by the browser.

Multiple selections use a compact dropdown with checkboxes and a summary of
the selected labels. Add/remove controls keep each mapping row compact.

Intermediate changes do not trigger automatic display-option submission.
**Apply** emits a change event on the containing form; ordinary form
submission also includes all mapping rows.

The mapping editor inherits from `BaseWidget`. Its `getValue()` returns ordered
key/value pairs so unfinished rows and duplicate keys survive serializable state
restoration. `setValue()` accepts pairs or a mapping object and restores child
widgets silently by default. Row edits emit `bloomerp:widget-change` with the
whole mapping; the display options form still submits only when Apply is clicked.

Custom lane order is persisted separately in `custom_group_order`, an ordered
list of names. The options form derives it from submitted mapping rows and uses
it to restore row order. The board and colour picker use the same list; JSON
object key order is never relied upon once this order has been saved. Older
preferences gain an explicit order on their next Apply. Small up/down buttons
beside the remove button move rows locally; Apply saves the new sequence.
