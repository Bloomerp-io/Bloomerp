"""Build analytics authoring schemas from the same definitions used by the editor."""

from copy import deepcopy
from typing import TYPE_CHECKING

from django import forms
from pydantic.json_schema import JsonSchemaValue

from bloomerp.workspaces.analytics_tile.utils import TileFieldType

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import (
        AnalyticsTileTypeDefinition, FieldDefinition, OptionDefinition,
    )


def option_schema(option: "OptionDefinition") -> JsonSchemaValue:
    """Describe an option and enumerate static or primitive-type-dependent choices."""
    schema: JsonSchemaValue = {
        "title": str(option.label),
        "description": str(option.description),
        "type": "boolean" if issubclass(option.field_cls, forms.BooleanField) else "string",
    }
    if option.restrict_to:
        schema["x-field-types"] = [item.value.key for item in option.restrict_to]
    choices = option.field_args.get("choices")
    if option.choices_provider is not None:
        choices_by_type = {
            primitive.value.key: [str(value) for value, _ in option.choices_provider(primitive)]
            for primitive in TileFieldType
        }
        schema["x-choices-by-field-type"] = choices_by_type
        schema["enum"] = list(dict.fromkeys(
            value for values in choices_by_type.values() for value in values
        ))
    elif choices is not None:
        schema["enum"] = [str(value) for value, _ in choices]
    return schema


def options_schema(options: list["OptionDefinition"]) -> JsonSchemaValue:
    """Describe only the declared options without treating editor suggestions as defaults."""
    return {
        "type": "object",
        "properties": {option.key: option_schema(option) for option in options},
        "additionalProperties": False,
        "default": {},
    }


def field_slot_schema(definition: "FieldDefinition") -> JsonSchemaValue:
    """Describe query-column selections, cardinality, and per-column options for a slot."""
    schema: JsonSchemaValue = {
        "type": "array",
        "title": str(definition.label),
        "description": str(definition.description),
        "minItems": definition.min_items,
        "items": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string", "minLength": 1,
                    "description": "Exact column name or alias returned by the tile query.",
                },
                "opts": options_schema(definition.opts),
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    }
    if not definition.allow_multiple:
        schema["maxItems"] = 1
    if definition.restrict_to:
        allowed = [item.value.key for item in definition.restrict_to]
        schema["x-field-types"] = allowed
        schema["description"] += f" Query column types must be one of: {', '.join(allowed)}."
    return schema


def analytics_config_schema(
    schema: JsonSchemaValue, definitions: list["AnalyticsTileTypeDefinition"],
) -> JsonSchemaValue:
    """Replace flexible dictionaries with subtype-specific oneOf authoring contracts."""
    result = deepcopy(schema)
    for name in ("type", "fields", "opts"):
        result["properties"].pop(name, None)
    result["oneOf"] = []
    for definition in definitions:
        fields: JsonSchemaValue = {
            "type": "object",
            "properties": {
                slot.key: field_slot_schema(slot) for slot in definition.fields
            },
            "additionalProperties": False,
        }
        required_slots = [slot.key for slot in definition.fields if slot.min_items > 0]
        if required_slots:
            fields["required"] = required_slots
        result["oneOf"].append({
            "title": str(definition.name),
            "description": str(definition.description),
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": definition.key},
                "fields": fields,
                "opts": options_schema(definition.opts),
            },
            "required": ["type", "fields"],
        })
    return result
