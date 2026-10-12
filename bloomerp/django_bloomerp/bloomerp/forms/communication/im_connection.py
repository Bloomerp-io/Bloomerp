"""Generate connection setup controls from the selected provider's typed schema."""

from typing import Any

from django import forms
from pydantic import SecretStr, ValidationError

from bloomerp.communication.builtins.instant_messaging.definition import (
    IMConnectionConfiguration,
    IMProviderDefinition,
)
from bloomerp.forms.agents.ai_agent import schema_form_field


class IMConnectionForm(forms.Form):
    """Validate provider configuration without keeping secret inputs in session state."""

    def __init__(
        self, *args: Any, provider: IMProviderDefinition, **kwargs: Any
    ) -> None:
        """Build the provider's typed fields using the existing schema form mapper."""
        super().__init__(*args, **kwargs)
        self.provider = provider
        self.configuration: IMConnectionConfiguration | None = None
        schema = provider.config_schema.model_json_schema()
        for name, definition in schema.get("properties", {}).items():
            self.fields[name] = schema_form_field(
                definition, name in schema.get("required", [])
            )
            if definition.get("writeOnly"):
                self.fields[name].initial = None
                self.fields[name].widget = forms.PasswordInput(
                    render_value=False,
                    attrs={"autocomplete": "new-password"},
                )

    def clean(self) -> dict[str, Any]:
        """Apply Pydantic constraints and map errors without echoing secret values."""
        data = super().clean()
        if self.errors:
            return data
        try:
            self.configuration = self.provider.config_schema.model_validate(data)
        except ValidationError as error:
            for issue in error.errors(include_input=False):
                name = str(issue["loc"][0]) if issue["loc"] else None
                self.add_error(
                    name if name in self.fields else None, "Check this value."
                )
        return data

    def split_configuration(self) -> tuple[dict[str, Any], dict[str, str]]:
        """Separate typed non-secret settings from credentials for encrypted persistence."""
        if self.configuration is None:
            raise ValueError("Validate the form first")
        settings: dict[str, Any] = {}
        credentials: dict[str, str] = {}
        for name in type(self.configuration).model_fields:
            value = getattr(self.configuration, name)
            if isinstance(value, SecretStr):
                if value.get_secret_value():
                    credentials[name] = value.get_secret_value()
            elif name != "name":
                settings[name] = self.configuration.model_dump(mode="json")[name]
        return settings, credentials
