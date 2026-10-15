from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal
from uuid import uuid4

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class BehaviorSchemaModel(BaseModel):
    """Base model for behavior configuration stored by the frontend."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class BehaviorEvent(str, Enum):
    CHANGE = "change"
    INITIAL = "initial"


class BehaviorConnector(str, Enum):
    ALL = "all"
    ANY = "any"


class BehaviorOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "not_empty"
    CONTAINS = "contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


class BehaviorResolver(str, Enum):
    ISO_WEEK_DAYS = "iso_week_days"
    ISO_WEEK = "iso_week"
    BLANK_ROWS = "blank_rows"
    COPY_RELATED_ROWS = "copy_related_rows"


class BehaviorWritePolicy(str, Enum):
    IF_EMPTY = "if_empty"
    REPLACE_GENERATED = "replace_generated"
    ALWAYS = "always"


class BehaviorMessageTone(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _behavior_id() -> str:
    """Create a stable identifier for behavior configuration assembled in Python."""

    return str(uuid4())


class BehaviorCondition(BehaviorSchemaModel):
    id: str = Field(default_factory=_behavior_id, min_length=1)
    field: str = Field(min_length=1)
    operator: BehaviorOperator = BehaviorOperator.EQUALS
    value: str = ""


class BehaviorActionBase(BehaviorSchemaModel):
    """Shared action fields while accepting the frontend's legacy wide payload."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    id: str = Field(default_factory=_behavior_id, min_length=1)


class TargetFieldAction(BehaviorActionBase):
    target_field: str = Field(min_length=1)


class ShowFieldAction(TargetFieldAction):
    type: Literal["show_field"] = "show_field"


class HideFieldAction(TargetFieldAction):
    type: Literal["hide_field"] = "hide_field"


class EnableFieldAction(TargetFieldAction):
    type: Literal["enable_field"] = "enable_field"


class DisableFieldAction(TargetFieldAction):
    type: Literal["disable_field"] = "disable_field"


class RequireFieldAction(TargetFieldAction):
    type: Literal["require_field"] = "require_field"


class MakeOptionalAction(TargetFieldAction):
    type: Literal["make_optional"] = "make_optional"


class SetValueAction(TargetFieldAction):
    type: Literal["set_value"] = "set_value"
    value: str = ""


class ClearValueAction(TargetFieldAction):
    type: Literal["clear_value"] = "clear_value"


class CopyValueAction(TargetFieldAction):
    type: Literal["copy_value"] = "copy_value"
    source_field: str = Field(min_length=1)


class CopyValueFromOneToManyAction(TargetFieldAction):
    type: Literal["copy_value_from_one_to_many"] = "copy_value_from_one_to_many"
    aggregation: Literal[
        "sum",
        "average",
        "count",
        "min",
        "max",
        "first",
        "last",
    ] = "count"
    source_field: str = Field(min_length=1)
    column_name: str = ""

    @model_validator(mode="after")
    def validate_aggregation_column(self) -> "CopyValueFromOneToManyAction":
        """Require a column for aggregations other than row count."""
        if self.aggregation != "count" and not self.column_name:
            raise ValueError(_("This aggregation requires a one-to-many column."))
        return self


class PopulateRowsAction(TargetFieldAction):
    type: Literal["populate_rows"] = "populate_rows"
    source_field: str = ""
    resolver: BehaviorResolver = BehaviorResolver.BLANK_ROWS
    row_count: int = Field(default=5, ge=1, le=100)
    write_policy: BehaviorWritePolicy = BehaviorWritePolicy.REPLACE_GENERATED

    @model_validator(mode="after")
    def validate_copy_source(self) -> "PopulateRowsAction":
        """Require a source field only when rows are copied from another field."""

        if (
            self.resolver == BehaviorResolver.COPY_RELATED_ROWS
            and not self.source_field
        ):
            raise ValueError(_("Copy-related-rows actions require a source field."))
        return self


class FilterChoicesAction(TargetFieldAction):
    """Compatibility model for configurations saved before this action is removed."""

    type: Literal["filter_choices"] = "filter_choices"


class ShowMessageAction(BehaviorActionBase):
    type: Literal["show_message"] = "show_message"
    value: str = ""
    message_tone: BehaviorMessageTone = BehaviorMessageTone.INFO


BehaviorAction = Annotated[
    ShowFieldAction
    | HideFieldAction
    | EnableFieldAction
    | DisableFieldAction
    | RequireFieldAction
    | MakeOptionalAction
    | SetValueAction
    | ClearValueAction
    | CopyValueAction
    | CopyValueFromOneToManyAction
    | PopulateRowsAction
    | FilterChoicesAction
    | ShowMessageAction,
    Field(discriminator="type"),
]


class BehaviorRule(BehaviorSchemaModel):
    id: str = Field(default_factory=_behavior_id, min_length=1)
    name: str = ""
    enabled: bool = True
    events: list[BehaviorEvent] = Field(
        default_factory=lambda: [BehaviorEvent.CHANGE],
        min_length=1,
    )
    connector: BehaviorConnector = BehaviorConnector.ALL
    conditions: list[BehaviorCondition] = Field(default_factory=list)
    actions: list[BehaviorAction] = Field(min_length=1)


class BehaviorConfig(BehaviorSchemaModel):
    """Validated configuration consumed by the behavior runtime."""

    rules: list[BehaviorRule] = Field(default_factory=list)

    def to_storage(self) -> dict[str, object]:
        """Serialize using the camelCase keys expected by the TypeScript runtime."""

        return self.model_dump(mode="json", by_alias=True)
