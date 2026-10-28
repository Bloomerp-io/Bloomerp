# Searchable choice widget

Use `ChoiceWidget` with Django choice fields when users need to search a fixed
list and see selections inside the field. Labels are searched locally; the
widget does not request related objects or allow creating new choices.

```python
from django import forms
from bloomerp.widgets.choice_widget import ChoiceWidget


class AssignmentForm(forms.Form):
    """Choose one priority and any number of fixed categories."""

    priority = forms.ChoiceField(
        choices=[("", "Choose a priority"), ("low", "Low"), ("high", "High")],
        widget=ChoiceWidget(),
    )
    categories = forms.MultipleChoiceField(
        choices=[("sales", "Sales"), ("support", "Support")],
        widget=ChoiceWidget(allow_multiple=True),
        required=False,
    )
```

`allow_multiple` defaults to false and can also be supplied in widget `attrs`.
Use `MultipleChoiceField` when enabling it so Django validates a list of values.
Grouped choices, initial selections, disabled fields, and required-field
validation retain native select semantics. Without JavaScript, the native
select remains usable. The component uses BloomERP's standard frontend bundle.

Type to filter, use the arrow keys and Enter to select, Escape to close results,
and the removal buttons to clear selections. Single selection replaces the
previous choice; multiple selection retains the other choices. Native `change`
and `bloomerp:widget-change` events notify form listeners. Programmatic
`getValue`/`setValue` and the base widget's serializable state support form history.
Existing choice widgets are not automatically replaced.
