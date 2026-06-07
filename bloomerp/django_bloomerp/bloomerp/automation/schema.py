from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from django.db import models


@dataclass
class WorkflowValueField:
    path: str
    label: str
    value_type: Literal["unknown"] = "unknown"
    children: list["WorkflowValueField"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "value_type": self.value_type,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class WorkflowIOSchema:
    kind: Literal["any", "object", "list", "fanout", "none", "branch_stopped"] = "any"
    label: str = ""
    description: str = ""
    fields: list[WorkflowValueField] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "fields": [field.to_dict() for field in self.fields],
        }


@dataclass
class WorkflowInputRequirement:
    kind: Literal["any", "object", "list", "fanout", "none"] = "any"
    label: str = ""
    description: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "required": self.required,
        }

    def accepts(self, incoming_schema: WorkflowIOSchema | None) -> bool:
        if self.kind == "any":
            return True
        if incoming_schema is None:
            return not self.required or self.kind == "none"
        if self.kind == "none":
            return incoming_schema.kind == "none"
        if self.kind == "object" and incoming_schema.kind == "fanout":
            return True
        return incoming_schema.kind == self.kind


def field_type_for_django_field(field: models.Field) -> str:
    if isinstance(field, (models.EmailField, models.CharField, models.TextField, models.SlugField, models.URLField)):
        return "string"
    if isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
        return "number"
    if isinstance(field, models.BooleanField):
        return "boolean"
    if isinstance(field, (models.DateField, models.DateTimeField, models.TimeField)):
        return "datetime"
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return "object"
    return "unknown"


def model_fields_to_value_fields(
    model: type[models.Model],
    path_prefix: str,
) -> list[WorkflowValueField]:
    return [
        WorkflowValueField(
            path=f"{path_prefix}.{field.name}",
            label=str(field.verbose_name).title(),
            value_type=field_type_for_django_field(field),
        )
        for field in model._meta.fields
    ]


def flatten_schema_fields(schema: WorkflowIOSchema) -> list[dict[str, str]]:
    flattened: list[dict[str, str]] = []

    def _walk(fields: list[WorkflowValueField]) -> None:
        for value_field in fields:
            flattened.append(
                {
                    "path": value_field.path,
                    "label": value_field.label,
                    "value_type": value_field.value_type,
                }
            )
            _walk(value_field.children)

    _walk(schema.fields)
    return flattened


def clone_schema_field_with_path(field: WorkflowValueField, path: str) -> WorkflowValueField:
    return WorkflowValueField(
        path=path,
        label=field.label,
        value_type=field.value_type,
        children=[
            clone_schema_field_with_path(
                child,
                child.path.replace(field.path, path, 1) if child.path.startswith(field.path) else child.path,
            )
            for child in field.children
        ],
    )


def remap_schema_field_paths(
    fields: list[WorkflowValueField],
    replacements: dict[str, str],
) -> list[WorkflowValueField]:
    remapped: list[WorkflowValueField] = []
    for field in fields:
        path = field.path
        for source, target in replacements.items():
            if path == source or path.startswith(f"{source}."):
                path = path.replace(source, target, 1)
                break

        remapped.append(
            WorkflowValueField(
                path=path,
                label=field.label,
                value_type=field.value_type,
                children=remap_schema_field_paths(field.children, replacements),
            )
        )
    return remapped
