from bloomerp.widgets.ordered_field_select_widget import OrderedFieldSelectWidget


from django import forms


class OrderedMultipleChoiceField(forms.MultipleChoiceField):
    widget = OrderedFieldSelectWidget

    def __init__(self, *args, required_values=None, **kwargs):
        self.required_values = [str(value) for value in (required_values or [])]
        super().__init__(*args, **kwargs)
        self.widget.required_values = set(self.required_values)

    def clean(self, value):
        cleaned = super().clean(value)
        for required_value in self.required_values:
            if required_value not in cleaned:
                cleaned.append(required_value)
        valid_values = {str(choice_value) for choice_value, _label in self.choices}
        return [
            field_name
            for field_name in cleaned
            if str(field_name) in valid_values
        ]