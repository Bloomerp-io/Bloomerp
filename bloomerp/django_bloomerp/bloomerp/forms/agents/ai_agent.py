"""Structured creation inputs derived from registered AI provider schemas."""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlsplit

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import BooleanField, F, QuerySet, Value
from django.forms.boundfield import BoundField
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ValidationError

from bloomerp.agents.definition import ModelModalities
from bloomerp.agents.providers.definition import AIProviderDefinition
from bloomerp.agents.resource_access import internal_resource_choices
from bloomerp.agents.tool_access import internal_tool_choices
from bloomerp.field_types.registry import FieldContext
from bloomerp.models.agents import AIAgent, MCPIntegration
from bloomerp.models.agents.ai_agent import model_modalities_form_field
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name

_MODALITIES_POST_KEYS = ("modalities", "modalities__present", "modalities__rows")


class LinesField(forms.CharField):
    """Accept a string list as one entry per line rather than requiring JSON."""

    def to_python(self, value: Any) -> list[str] | None:
        """Normalize nonempty lines into the provider's array representation."""
        text = super().to_python(value)
        return [line.strip() for line in text.splitlines() if line.strip()] or None

    def prepare_value(self, value: Any) -> Any:
        """Render provider array defaults as readable lines rather than Python list syntax."""
        return "\n".join(value) if isinstance(value, list) else value


def schema_form_field(property_schema: dict[str, Any], required: bool) -> forms.Field:
    """Build a typed scalar or string-list control using Pydantic JSON schema metadata."""
    schema = dict(property_schema)
    variants = schema.get("anyOf", [])
    if variants:
        schema.update(
            next((variant for variant in variants if variant.get("type") != "null"), {})
        )
    options: dict[str, Any] = {
        "required": required,
        "label": schema.get("title", ""),
        "help_text": schema.get("description", ""),
        "initial": schema.get("default"),
    }
    choices = schema.get("enum")
    if choices:
        return forms.ChoiceField(
            choices=[
                ("", _("Provider default")),
                *[(value, value) for value in choices],
            ],
            **options,
        )
    kind = schema.get("type")
    if kind == "boolean":
        widget = forms.NullBooleanSelect()
        widget.choices = [
            ("unknown", _("Provider default")),
            ("true", _("Yes")),
            ("false", _("No")),
        ]
        return forms.NullBooleanField(widget=widget, **options)
    if kind in {"integer", "number"}:
        options.update(min_value=schema.get("minimum"), max_value=schema.get("maximum"))
        if kind == "integer" and "exclusiveMinimum" in schema:
            options["min_value"] = schema["exclusiveMinimum"] + 1
        return (forms.IntegerField if kind == "integer" else forms.FloatField)(
            **options
        )
    if kind == "array" and schema.get("items", {}).get("type") == "string":
        options["help_text"] = schema.get("description") or _(
            "Enter one value per line."
        )
        return LinesField(widget=forms.Textarea(attrs={"rows": 3}), **options)
    if kind == "string":
        options.update(
            min_length=schema.get("minLength"), max_length=schema.get("maxLength")
        )
        if schema.get("writeOnly") or schema.get("format") == "password":
            options["widget"] = forms.PasswordInput(
                render_value=False, attrs={"autocomplete": "new-password"}
            )
        return forms.CharField(**options)
    raise ValueError(
        "Provider schemas must describe scalar fields or string lists for this form"
    )


def selectable_integrations(user: Any) -> QuerySet[MCPIntegration]:
    """Filter visible integration names and annotate optional label fields through row-sensitive grants."""
    if user is None:
        return MCPIntegration.objects.none()
    manager = UserPolicyManager(user)
    queryset = manager.get_accessible_queryset(MCPIntegration, "view")
    if user.is_superuser:
        return queryset
    metadata = {
        item.field: item
        for item in ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(MCPIntegration),
            field__in=["name", "connection_mode", "enabled"],
        )
    }
    if "name" not in metadata:
        return queryset.none()
    queryset = manager.annotate_field_permissions(
        queryset, list(metadata.values()), "view"
    )
    queryset = queryset.filter(**{field_access_annotation_name(metadata["name"]): True})
    return queryset.annotate(
        _integration_mode_visible=F(
            field_access_annotation_name(metadata["connection_mode"])
        )
        if "connection_mode" in metadata
        else Value(False, output_field=BooleanField()),
        _integration_enabled_visible=F(
            field_access_annotation_name(metadata["enabled"])
        )
        if "enabled" in metadata
        else Value(False, output_field=BooleanField()),
    )


class IntegrationSelectionField(forms.ModelMultipleChoiceField):
    """Label integration definitions with their account connection mode."""

    def label_from_instance(self, obj: MCPIntegration) -> str:
        """Distinguish shared and personal integrations without exposing connections."""
        details = []
        if getattr(obj, "_integration_mode_visible", True):
            details.append(str(obj.get_connection_mode_display()))
        if getattr(obj, "_integration_enabled_visible", True) and not obj.enabled:
            details.append(str(_("Disabled")))
        return f"{obj.name} ({', '.join(details)})" if details else obj.name


class AIAgentDetailsForm(forms.ModelForm):
    """Collect model settings, credentials, and parameters without raw JSON inputs."""

    modalities = model_modalities_form_field(
        FieldContext(), AIAgent._meta.get_field("modalities").formfield()
    )
    internal_tools = forms.MultipleChoiceField(
        required=False,
        label=_("Selected built-in Bloomerp tools"),
        help_text=_(
            "Used only for selected tool access. Leave empty to allow no built-in tools. Unavailable names are retained but cannot run."
        ),
        widget=forms.SelectMultiple(attrs={"size": 10}),
    )
    internal_resources = forms.MultipleChoiceField(
        required=False,
        label=_("Selected built-in Bloomerp resources"),
        help_text=_(
            "Used only for selected resource access. Leave empty to allow no resources. Resources are exposed to the agent as read-only tools. Unavailable URIs are retained but cannot be read."
        ),
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )
    mcp_integrations = IntegrationSelectionField(
        queryset=MCPIntegration.objects.none(),
        required=False,
        label=_("External MCP integrations"),
        help_text=AIAgent._meta.get_field("mcp_integrations").help_text,
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    class Meta:
        model = AIAgent
        fields: ClassVar[list[str]] = [
            "name",
            "model_identifier",
            "modalities",
            "default_instructions",
            "enabled",
            "internal_tool_mode",
            "internal_tools",
            "internal_resource_mode",
            "internal_resources",
            "mcp_integrations",
            "base_url",
            "request_timeout_seconds",
            "max_tokens",
            "max_tool_calls",
            "max_duration_seconds",
        ]
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "default_instructions": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(
        self,
        *args: Any,
        provider: AIProviderDefinition,
        allowed_fields: set[str] | None = None,
        user: Any = None,
        **kwargs: Any,
    ) -> None:
        """Generate provider controls and omit settings outside the actor's field grants."""
        super().__init__(*args, **kwargs)
        self.fields["internal_tool_mode"].required = False
        self.fields["internal_resource_mode"].required = False
        resource_choices = internal_resource_choices()
        live_uris = {uri for uri, label in resource_choices}
        resource_choices.extend(
            (uri, str(_("Unavailable resource: %(uri)s")) % {"uri": uri})
            for uri in self.instance.internal_resources
            if uri not in live_uris
        )
        self.fields["internal_resources"].choices = resource_choices
        choices = internal_tool_choices()
        live_names = {name for name, label in choices}
        choices.extend(
            (name, str(_("Unavailable tool: %(name)s")) % {"name": name})
            for name in self.instance.internal_tools
            if name not in live_names
        )
        self.fields["internal_tools"].choices = choices
        integrations = selectable_integrations(user)
        self.fields["mcp_integrations"].queryset = integrations.order_by("name", "pk")
        self.hidden_integration_ids = set()
        if not self.instance._state.adding:
            visible_ids = set(integrations.values_list("pk", flat=True))
            selected_ids = set(
                self.instance.mcp_integrations.values_list("pk", flat=True)
            )
            self.hidden_integration_ids = selected_ids - visible_ids
            self.initial["mcp_integrations"] = list(selected_ids & visible_ids)
        self.provider = provider
        self.original_model = (
            self.instance.provider,
            self.instance.model_identifier,
            self.instance.base_url or None,
        )
        if provider.model_modalities_factory is not None:
            self.fields["discover_modalities"] = forms.BooleanField(
                required=False,
                label=_("Discover model modalities on save"),
                help_text=_(
                    "Replace the mapping with the selected provider's model capabilities."
                ),
            )
        self.keep_credentials = (
            not self.instance._state.adding
            and self.instance.provider == provider.id
            and bool(self.instance.credentials_encrypted)
        )
        existing_parameters = (
            self.instance.parameters
            if not self.instance._state.adding and self.instance.provider == provider.id
            else {}
        )
        self.instance.provider = provider.id
        self.schema_fields: dict[str, dict[str, str]] = {}
        self.credentials: dict[str, Any] = {}
        for root, schema_class, prefix in [
            ("credentials_encrypted", provider.credentials_schema, "credential"),
            ("parameters", provider.config_schema, "parameter"),
        ]:
            schema = schema_class.model_json_schema()
            self.schema_fields[root] = {}
            if allowed_fields is not None and root not in allowed_fields:
                continue
            for name, property_schema in schema.get("properties", {}).items():
                if name in schema.get("form_exclude", []):
                    continue
                field_name = f"{prefix}__{name}"
                self.fields[field_name] = schema_form_field(
                    property_schema, name in schema.get("required", [])
                )
                if root == "parameters" and name in existing_parameters:
                    self.initial[field_name] = existing_parameters[name]
                if root == "credentials_encrypted" and self.keep_credentials:
                    self.fields[field_name].required = False
                    self.fields[field_name].help_text = _(
                        "Leave blank to keep the stored value. Enter a value to replace it."
                    )
                    # Neither secret nor non-secret stored credential values are
                    # copied into HTML or session state.
                    self.fields[field_name].initial = None
                self.schema_fields[root][name] = field_name
        self.field_roots = {name: name for name in self.Meta.fields}
        self.field_roots.update(
            dict.fromkeys((*_MODALITIES_POST_KEYS, "discover_modalities"), "modalities")
        )
        for root, mapping in self.schema_fields.items():
            self.field_roots.update(
                {field_name: root for field_name in mapping.values()}
            )
        if allowed_fields is not None:
            for name in list(self.fields):
                if self.field_roots[name] not in allowed_fields:
                    self.fields.pop(name)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "input w-full")
        for name in (
            "request_timeout_seconds",
            "max_tokens",
            "max_tool_calls",
            "max_duration_seconds",
        ):
            if name in self.fields:
                self.fields[name].widget.attrs["min"] = 1

    def clean_internal_tool_mode(self) -> str:
        """Keep the current default when older callers omit the optional mode input."""
        return (
            self.cleaned_data.get("internal_tool_mode")
            or self.instance.internal_tool_mode
        )

    def clean_internal_resource_mode(self) -> str:
        """Preserve the current resource mode when older callers omit the input."""
        return (
            self.cleaned_data.get("internal_resource_mode")
            or self.instance.internal_resource_mode
        )

    def clean_mcp_integrations(self) -> QuerySet[MCPIntegration]:
        """Reject selections larger than the runtime's bounded integration discovery limit."""
        selected = self.cleaned_data["mcp_integrations"]
        if selected.count() + len(self.hidden_integration_ids) > 20:
            raise forms.ValidationError(
                _("Select at most 20 external MCP integrations per agent.")
            )
        return selected

    def _save_m2m(self) -> None:
        """Persist permitted selections while retaining existing integrations hidden by row grants."""
        if "mcp_integrations" in self.cleaned_data:
            selected = self.cleaned_data["mcp_integrations"]
            self.cleaned_data["mcp_integrations"] = MCPIntegration.objects.filter(
                pk__in=set(selected.values_list("pk", flat=True))
                | self.hidden_integration_ids
            )
        super()._save_m2m()

    def clean_base_url(self) -> str | None:
        """Reject credential-bearing endpoints before storing or calling the provider."""
        value = self.cleaned_data.get("base_url")
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise forms.ValidationError(
                    _(
                        "Use an HTTP endpoint without credentials, query parameters, or fragments."
                    )
                )
        return value or None

    def clean_modalities(self) -> dict[str, Any]:
        """Validate the input and output mapping using the shared modality enum."""
        value = self.cleaned_data["modalities"]
        if value is None or value == {}:
            return {}
        try:
            return ModelModalities.model_validate(value).model_dump(mode="json")
        except ValidationError as error:
            raise forms.ValidationError(
                _("Enter a valid model modality mapping.")
            ) from error

    def schema_values(self, root: str) -> dict[str, Any]:
        """Read nonempty typed inputs while leaving unspecified options to provider defaults."""
        return {
            name: self.cleaned_data[field_name]
            for name, field_name in self.schema_fields[root].items()
            if field_name in self.cleaned_data
            and self.cleaned_data[field_name] not in (None, "")
        }

    def validate_schema(
        self, root: str, schema_class: type[BaseModel], values: dict[str, Any]
    ) -> bool:
        """Attach schema errors to controls without reflecting submitted secret values."""
        try:
            schema_class.model_validate(values)
        except ValidationError as error:
            for item in error.errors(include_input=False):
                name = str(item["loc"][0]) if item["loc"] else ""
                field_name = self.schema_fields[root].get(name)
                message = (
                    _("Invalid credential value.")
                    if root == "credentials_encrypted"
                    else _("This value is not supported by the selected provider.")
                )
                self.add_error(field_name, message)
            return False
        return True

    def clean(self) -> dict[str, Any]:
        """Validate provider settings and reset unchanged modalities on model changes."""
        cleaned = super().clean()
        model = (
            self.provider.id,
            cleaned.get("model_identifier", self.instance.model_identifier),
            cleaned.get("base_url", self.instance.base_url) or None,
        )
        mapping_posted = any(
            self.add_prefix(name) in self.data for name in _MODALITIES_POST_KEYS
        )
        mapping_changed = mapping_posted and "modalities" in self.changed_data
        if "modalities" in cleaned and not mapping_changed:
            cleaned["modalities"] = self.instance.modalities
        if model != self.original_model and not mapping_changed:
            if "modalities" in cleaned:
                cleaned["modalities"] = {}
                self.instance.modalities = {}
            elif self.instance.modalities:
                self.add_error(
                    None, _("Changing this model requires access to its modalities.")
                )
        for name in (
            "request_timeout_seconds",
            "max_tokens",
            "max_tool_calls",
            "max_duration_seconds",
        ):
            value = cleaned.get(name)
            if value is not None and value <= 0:
                self.add_error(
                    name,
                    _(
                        "Enter a value greater than zero. Leave optional limits blank for no limit."
                    ),
                )
        submitted_credentials = self.schema_values("credentials_encrypted")
        self.credentials = submitted_credentials
        if self.schema_fields["credentials_encrypted"]:
            if self.keep_credentials and submitted_credentials:
                stored = self.instance.validated_credentials().model_dump()
                self.credentials = {
                    name: value.get_secret_value()
                    if hasattr(value, "get_secret_value")
                    else value
                    for name, value in stored.items()
                }
                self.credentials.update(submitted_credentials)
            if not self.keep_credentials or submitted_credentials:
                self.validate_schema(
                    "credentials_encrypted",
                    self.provider.credentials_schema,
                    self.credentials,
                )
        if self.schema_fields["parameters"]:
            parameters = self.schema_values("parameters")
            if self.validate_schema(
                "parameters", self.provider.config_schema, parameters
            ):
                self.instance.parameters = parameters
        return cleaned

    def discover_model_modalities(self, candidate: AIAgent) -> bool:
        """Apply provider discovery on an authorized candidate when requested."""
        discover = self.provider.model_modalities_factory
        if discover is None or not self.cleaned_data.get("discover_modalities"):
            return True
        if (
            not self.credentials
            and (candidate.base_url or None) != self.original_model[2]
        ):
            self.add_error(
                "discover_modalities", _("Enter credentials for the new endpoint.")
            )
            return False
        try:
            credentials = (
                self.provider.credentials_schema.model_validate(self.credentials)
                if self.credentials
                else candidate.validated_credentials()
            )
            modalities = discover(
                candidate.model_identifier, credentials, candidate.base_url
            )
        except (DjangoValidationError, ValueError):
            modalities = None
        if modalities is None:
            self.add_error(
                "discover_modalities",
                _(
                    "Capabilities could not be discovered. Check the model and endpoint or enter the mapping manually."
                ),
            )
            return False
        candidate.modalities = modalities.model_dump(mode="json")
        return True

    def group_fields(self, group: str) -> list[BoundField]:
        """Return visible inputs for one named section of the details page."""
        return [self[name] for name in self.fields if self.field_roots[name] == group]
