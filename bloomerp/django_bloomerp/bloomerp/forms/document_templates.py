from django import forms
from django.db.models import Model


from typing import Any


class DocumentTemplateForm(forms.Form):
    variable_field_names: tuple[str, ...] = ()
    variable_name_by_field_name: dict[str, str] = {}
    preset_instance: Model | None = None
    preset_variable_name: str | None = None

    persist = forms.BooleanField(
        initial=False,
        required=False,
        help_text="Save this document template",
        widget=forms.CheckboxInput(
            attrs={
                "class": "input",
            }
        )
    )

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if "persist" in self.fields:
            self.order_fields([field_name for field_name in self.fields if field_name != "persist"] + ["persist"])
        self.model_variable_values = {}
        if self.preset_instance is not None and self.preset_variable_name is not None:
            self.model_variable_values[self.preset_variable_name] = self.preset_instance
            self.instance = self.preset_instance
            self.objects = [self.preset_instance]
        else:
            self.instance = None
            self.objects = []

    def clean(self):
        cleaned_data = super().clean()
        model_variable_values = dict(getattr(self, "model_variable_values", {}))

        for field_name in self.variable_field_names:
            selected_instance = cleaned_data.get(field_name)
            if selected_instance is None:
                continue
            model_variable_values[self.variable_name_by_field_name[field_name]] = selected_instance

        self.model_variable_values = model_variable_values
        self.objects = list(model_variable_values.values())
        self.instance = self.objects[0] if self.objects else None
        return cleaned_data