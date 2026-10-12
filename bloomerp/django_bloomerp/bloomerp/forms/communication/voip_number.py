"""Render provider-defined number controls using the existing schema field mapper."""

from typing import Any
from django import forms
from django.utils.translation import gettext_lazy as _
from pydantic import ValidationError
from bloomerp.forms.agents.ai_agent import schema_form_field
from bloomerp.communication.builtins.voip.definition import VoIPNumberOptions


class VoIPNumberOptionsForm(forms.Form):
    """Build and validate carrier controls from a registered typed operation schema."""

    def __init__(
        self, *args: Any, schema: type[VoIPNumberOptions], **kwargs: Any
    ) -> None:
        """Reuse the schema mapper and retain the schema for authoritative validation."""
        super().__init__(*args, **kwargs)
        self.options_schema = schema
        self.options: dict[str, Any] = {}
        definition = schema.model_json_schema()
        for name, property_schema in definition.get("properties", {}).items():
            if name in self.fields:
                raise ValueError(
                    f"Provider option conflicts with a reserved field: {name}"
                )
            required = name in definition.get("required", [])
            self.fields[name] = schema_form_field(property_schema, required)
            if name in schema.field_choices:
                self.fields[name].choices = schema.field_choices[name]

    def clean(self) -> dict[str, Any]:
        """Validate only declared provider inputs and retain normalized operation options."""
        data = super().clean()
        if self.errors:
            return data
        values = {name: data[name] for name in self.options_schema.model_fields}
        try:
            self.options = self.options_schema.model_validate(values).model_dump(
                mode="json"
            )
        except ValidationError as error:
            for issue in error.errors(include_input=False):
                name = str(issue["loc"][0]) if issue["loc"] else None
                self.add_error(
                    name if name in self.fields else None, _("Check this value.")
                )
        return data


class VoIPNumberSearchForm(VoIPNumberOptionsForm):
    """Render the selected provider's availability criteria."""


class VoIPNumberPurchaseForm(VoIPNumberOptionsForm):
    """Keep signed selection and explicit consent outside carrier-defined options."""

    selection = forms.CharField(widget=forms.HiddenInput)
    name = forms.CharField(label=_("Label"), max_length=255, required=False)
    confirm = forms.BooleanField(
        label=_("Provision this number and accept the applicable provider charges.")
    )

    def __init__(
        self, *args: Any, schema: type[VoIPNumberOptions], **kwargs: Any
    ) -> None:
        """Place the shared confirmation after all provider-specific controls."""
        super().__init__(*args, schema=schema, **kwargs)
        self.fields["confirm"] = self.fields.pop("confirm")
