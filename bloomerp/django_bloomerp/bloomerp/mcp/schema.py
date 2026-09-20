from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from rest_framework import serializers
from rest_framework.fields import _UnvalidatedField

from bloomerp.mcp.definition import McpSchema


SchemaDirection = Literal["input", "output"]


def serializer_input_schema(
    serializer_class: type[serializers.BaseSerializer],
) -> McpSchema:
    """Build the JSON Schema advertised for a DRF serializer's input."""
    return _serializer_schema(serializer_class, direction="input")


def serializer_output_schema(
    serializer_class: type[serializers.BaseSerializer],
) -> McpSchema:
    """Build the JSON Schema advertised for a DRF serializer's output."""
    return _serializer_schema(serializer_class, direction="output")


def _serializer_schema(
    serializer_class: type[serializers.BaseSerializer],
    *,
    direction: SchemaDirection,
) -> McpSchema:
    if not isinstance(serializer_class, type) or not issubclass(
        serializer_class, serializers.BaseSerializer
    ):
        raise TypeError("serializer_class must be a DRF serializer class")

    serializer = serializer_class()
    schema = _field_schema(serializer, direction=direction)
    schema["additionalProperties"] = False
    return schema


def _field_schema(
    field: serializers.Field,
    *,
    direction: SchemaDirection,
) -> McpSchema:
    if isinstance(field, _UnvalidatedField):
        schema: McpSchema = {}
    elif isinstance(field, serializers.ListSerializer):
        schema: McpSchema = {
            "type": "array",
            "items": _field_schema(field.child, direction=direction),
        }
    elif isinstance(field, serializers.BaseSerializer):
        properties: dict[str, McpSchema] = {}
        required: list[str] = []

        for name, child in field.fields.items():
            if isinstance(child, serializers.HiddenField):
                continue
            if direction == "input" and child.read_only:
                continue
            if direction == "output" and child.write_only:
                continue

            properties[name] = _field_schema(child, direction=direction)
            if child.required:
                required.append(name)

        schema = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
    elif isinstance(field, serializers.MultipleChoiceField):
        schema = {
            "type": "array",
            "items": _choice_schema(field.choices),
            "uniqueItems": True,
        }
    elif isinstance(field, serializers.ChoiceField):
        schema = _choice_schema(field.choices)
    elif isinstance(field, serializers.ListField):
        schema = {
            "type": "array",
            "items": _field_schema(field.child, direction=direction),
        }
    elif isinstance(field, serializers.DictField):
        schema = {"type": "object"}
        if field.child is not None:
            schema["additionalProperties"] = _field_schema(
                field.child, direction=direction
            )
    elif isinstance(field, serializers.JSONField):
        schema = {}
    elif isinstance(field, serializers.BooleanField):
        schema = {"type": "boolean"}
    elif isinstance(field, serializers.IntegerField):
        schema = {"type": "integer"}
        _copy_attributes(
            field,
            schema,
            ("min_value", "minimum"),
            ("max_value", "maximum"),
        )
    elif isinstance(field, (serializers.FloatField, serializers.DecimalField)):
        schema = {"type": "number"}
        _copy_attributes(
            field,
            schema,
            ("min_value", "minimum"),
            ("max_value", "maximum"),
        )
    elif isinstance(field, serializers.UUIDField):
        schema = {"type": "string", "format": "uuid"}
    elif isinstance(field, serializers.DateTimeField):
        schema = {"type": "string", "format": "date-time"}
    elif isinstance(field, serializers.DateField):
        schema = {"type": "string", "format": "date"}
    elif isinstance(field, serializers.TimeField):
        schema = {"type": "string", "format": "time"}
    elif isinstance(field, serializers.EmailField):
        schema = {"type": "string", "format": "email"}
    elif isinstance(field, serializers.URLField):
        schema = {"type": "string", "format": "uri"}
    elif isinstance(field, serializers.IPAddressField):
        schema = {"type": "string"}
    elif isinstance(field, serializers.FileField):
        schema = {"type": "string", "contentEncoding": "base64"}
    elif isinstance(field, serializers.CharField):
        schema = {"type": "string"}
        _copy_attributes(
            field,
            schema,
            ("min_length", "minLength"),
            ("max_length", "maxLength"),
        )
    else:
        raise TypeError(
            f"Unsupported DRF field for MCP schema generation: {type(field).__name__}"
        )

    if field.help_text:
        schema["description"] = str(field.help_text)
    if field.label and field.label != field.field_name.replace("_", " ").title():
        schema["title"] = str(field.label)
    if field.default is not serializers.empty and not callable(field.default):
        schema["default"] = field.default
    if field.allow_null:
        schema = {"anyOf": [schema, {"type": "null"}]}

    return schema


def _choice_schema(choices: Mapping[Any, Any]) -> McpSchema:
    values = list(choices.keys())
    non_null_values = [value for value in values if value is not None]
    value_types = {type(value) for value in non_null_values}

    schema: McpSchema = {"enum": values}
    if not non_null_values or len(value_types) != 1:
        return schema

    value_type = next(iter(value_types))
    if value_type is bool:
        schema["type"] = "boolean"
    elif value_type is int:
        schema["type"] = "integer"
    elif value_type is float:
        schema["type"] = "number"
    elif value_type is str:
        schema["type"] = "string"
    return schema


def _copy_attributes(
    field: serializers.Field,
    schema: McpSchema,
    *attributes: tuple[str, str],
) -> None:
    for field_attribute, schema_attribute in attributes:
        value = getattr(field, field_attribute, None)
        if value is not None:
            schema[schema_attribute] = value
