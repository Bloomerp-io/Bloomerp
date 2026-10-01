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

In display options, select the grouping field first, then add named custom
mappings and click **Apply**. The colour editor lists the resulting
lanes after the grouping is saved. While dragging, each grouped lane exposes
its individual destinations. Its **Move to** selector controls the destination
for a drop into the lane body and for keyboard moves. Dropping onto an individual
destination always uses that value, including within the card's current lane.

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
