from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from django.db import models


class WorkflowValueType(StrEnum):
    UNKNOWN = "unknown"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    OBJECT = "object"
    LIST = "list"
    ANY = "any"
    NONE = "none"

    @property
    def label(self) -> str:
        return {
            self.UNKNOWN: "Unknown",
            self.STRING: "Text",
            self.NUMBER: "Number",
            self.BOOLEAN: "True/False",
            self.DATETIME: "Date/Time",
            self.OBJECT: "Object",
            self.LIST: "List",
            self.ANY: "Any type",
            self.NONE: "No value",
        }[self]

    @property
    def icon(self) -> str:
        return {
            self.UNKNOWN: "fa-solid fa-circle-question",
            self.STRING: "fa-solid fa-font",
            self.NUMBER: "fa-solid fa-hashtag",
            self.BOOLEAN: "fa-solid fa-toggle-on",
            self.DATETIME: "fa-solid fa-clock",
            self.OBJECT: "fa-solid fa-cube",
            self.LIST: "fa-solid fa-list",
            self.ANY: "fa-solid fa-asterisk",
            self.NONE: "fa-solid fa-ban",
        }[self]


class WorkflowIOFlowKind(StrEnum):
    NORMAL = "normal"
    FANOUT = "fanout"
    CONDITION_GATE = "condition_gate"

    @property
    def label(self) -> str:
        return {
            self.NORMAL: "Passes values once",
            self.FANOUT: "Runs next nodes once per item",
            self.CONDITION_GATE: "May stop this branch",
        }[self]

    @property
    def icon(self) -> str:
        return {
            self.NORMAL: "fa-solid fa-arrow-right",
            self.FANOUT: "fa-solid fa-repeat",
            self.CONDITION_GATE: "fa-solid fa-code-branch",
        }[self]


def _coerce_enum(enum_cls, value):
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


@dataclass
class WorkflowValueField:
    path: str
    label: str
    value_type: WorkflowValueType = WorkflowValueType.UNKNOWN
    description: Optional[str] = None
    children: list["WorkflowValueField"] = field(default_factory=list)
    optional: bool = False
        
    def __post_init__(self) -> None:
        self.value_type = _coerce_enum(WorkflowValueType, self.value_type)

    @property
    def template_token_path(self) -> str:
        if self.path == "input" or self.path.startswith("input."):
            return self.path
        return f"input.{self.path}"

    @property
    def template_token(self) -> str:
        return f"{{{{ {self.template_token_path} }}}}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "value_type": self.value_type.value,
            "template_token": self.template_token,
            "optional": self.optional,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class WorkflowIOSchema:
    value_type: WorkflowValueType = WorkflowValueType.ANY
    flow_kind: WorkflowIOFlowKind = WorkflowIOFlowKind.NORMAL
    label: str = ""
    description: str = ""
    fields: list[WorkflowValueField] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.value_type = _coerce_enum(WorkflowValueType, self.value_type)
        self.flow_kind = _coerce_enum(WorkflowIOFlowKind, self.flow_kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_type": self.value_type.value,
            "flow_kind": self.flow_kind.value,
            "label": self.label,
            "description": self.description,
            "fields": [field.to_dict() for field in self.fields],
        }

    def get_field_by_path(self, path: str) -> Optional[WorkflowValueField]:
        """Retrieves the field by path name

        Args:
            path (str): the field path (i.e. first_name, )
            search_children (bool, optional): _description_. Defaults to False.

        Returns:
            Optional[WorkflowValueField]: _description_
        """
        def _walk(fields: list[WorkflowValueField]) -> Optional[WorkflowValueField]:
            for field in fields:
                if field.path == path:
                    return field

                child = _walk(field.children)
                if child:
                    return child

            return None

        return _walk(self.fields)
    

@dataclass
class WorkflowInputRequirement:
    value_type: WorkflowValueType = WorkflowValueType.ANY
    label: str = ""
    description: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        self.value_type = _coerce_enum(WorkflowValueType, self.value_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_type": self.value_type.value,
            "label": self.label,
            "description": self.description,
            "required": self.required,
        }

    def accepts(self, incoming_schema: WorkflowIOSchema | None) -> bool:
        if self.value_type == WorkflowValueType.ANY:
            return True
        if incoming_schema is None:
            return not self.required or self.value_type == WorkflowValueType.NONE
        if self.value_type == WorkflowValueType.NONE:
            return incoming_schema.value_type == WorkflowValueType.NONE
        return incoming_schema.value_type == self.value_type



def flatten_schema_fields(schema: WorkflowIOSchema) -> list[dict[str, str]]:
    flattened: list[dict[str, str]] = []

    def _walk(fields: list[WorkflowValueField]) -> None:
        for value_field in fields:
            flattened.append(
                {
                    "path": value_field.path,
                    "label": value_field.label,
                    "value_type": value_field.value_type.value,
                    "template_token": value_field.template_token,
                    "optional": value_field.optional,
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
        description=field.description,
        optional=field.optional,
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
                description=field.description,
                optional=field.optional,
                children=remap_schema_field_paths(field.children, replacements),
            )
        )
    return remapped
