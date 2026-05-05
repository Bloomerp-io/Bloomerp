# -------------------------
# Display options
# -------------------------

from django import forms


class OrderedFieldSelectWidget(forms.Widget):
    template_name = "widgets/ordered_field_select_widget.html"

    def __init__(self, attrs=None, choices=(), required_values=None):
        super().__init__(attrs)
        self.choices = list(choices)
        self.required_values = {str(value) for value in (required_values or [])}

    def format_value(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    def value_from_datadict(self, data, files, name):
        return data.getlist(name)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        selected_values = self.format_value(value)
        selected_set = set(selected_values)
        choice_map = {str(choice_value): choice_label for choice_value, choice_label in self.choices}
        ordered_values = [
            field_name
            for field_name in selected_values
            if field_name in choice_map
        ]
        ordered_values.extend(
            str(choice_value)
            for choice_value, _label in self.choices
            if str(choice_value) in self.required_values and str(choice_value) not in ordered_values
        )
        ordered_values.extend(
            str(choice_value)
            for choice_value, _label in self.choices
            if str(choice_value) not in ordered_values
        )
        context["widget"]["options"] = [
            {
                "name": name,
                "value": field_name,
                "label": choice_map[field_name],
                "selected": field_name in selected_set or field_name in self.required_values,
                "required": field_name in self.required_values,
                "index": index,
            }
            for index, field_name in enumerate(ordered_values)
        ]
        return context