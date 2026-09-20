"""Draft action API: validated configuration in, field updates out.

Execution is independent of Django widgets and never saves model instances.
Authorization, rule matching and cascading belong to the future engine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from bloomerp.filters.definition import Filter

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField

    TargetField = ApplicationField | None
    ListenerField = ApplicationField | None

CleanedConfigData = Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class BehaviorFieldReference:
    """Declare an action configuration field and its required access level."""

    field: ApplicationField
    permission: Literal["view", "change"] = "view"


@dataclass(frozen=True, kw_only=True)
class BehaviorContext:
    """Current draft values, keyed by field name (including unsaved values).

    The caller supplies a snapshot and resolves/authorizes the target. Actions
    must not mutate values in this context. No widget or DOM identifiers occur.
    """

    values: Mapping[str, Any]
    listener_field: str  # Trigger field; action sources are configured separately.
    target_field: str = ""  # Empty for actions without an explicit target.
    resolve_related_values: Callable[
        [ApplicationField, ApplicationField, tuple[Any, ...]], Mapping[str, Any]
    ] | None = None

    @property
    def listener_value(self) -> Any:
        """Return the triggering field's current draft value."""
        return self.values.get(self.listener_field)

    @property
    def target_value(self) -> Any:
        """Return the selected target's current draft value."""
        return self.values.get(self.target_field)


@dataclass(frozen=True, kw_only=True)
class FieldValueUpdate:
    field: str
    value: Any


@dataclass(frozen=True, kw_only=True)
class FieldStateUpdate:
    """Set target visibility and interaction state without changing its value."""

    field: str
    visible: bool | None = None
    disabled: bool = False


@dataclass(frozen=True, kw_only=True)
class BehaviorMessage:
    type: Literal["info", "warning", "danger", "success"]
    message: str


@dataclass(frozen=True, kw_only=True)
class BehaviorResult:
    """Whole field values and presentation state for a generic client adapter.

    Values use the target field's public value schema. Serialization is the
    endpoint's responsibility, using the field's existing value serializer.
    """

    values: tuple[FieldValueUpdate, ...] = ()
    states: tuple[FieldStateUpdate, ...] = ()
    messages: tuple[BehaviorMessage, ...] = ()


class EmptyConfigForm(forms.Form):
    pass


def empty_config_form_factory(
    target: ApplicationField | None, listener: ApplicationField | None
) -> type[forms.Form]:
    """Return a configuration form for actions without additional options."""
    return EmptyConfigForm


def all_listener_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Accept any field in the caller's scoped listener queryset."""
    return fields


def all_target_fields(
    fields: QuerySet[ApplicationField], listener: ApplicationField | None
) -> QuerySet[ApplicationField]:
    """Accept any field in the caller's scoped target queryset."""
    return fields


@dataclass(frozen=True, kw_only=True)
class BehaviorActionDefinition:
    id: str
    label: str
    description: str
    requires_target_field: bool
    execute: Callable[[BehaviorContext, CleanedConfigData], BehaviorResult]
    config_form_factory: Callable[
        [TargetField, ListenerField], type[forms.Form]
    ] = empty_config_form_factory
    get_listener_fields: Callable[
        [QuerySet[ApplicationField]], QuerySet[ApplicationField]
    ] = all_listener_fields
    get_target_fields: Callable[
        [QuerySet[ApplicationField], ApplicationField | None],
        QuerySet[ApplicationField],
    ] = all_target_fields

    def run(
        self,
        context: BehaviorContext,
        config: Mapping[str, Any] | None = None,
        *,
        target: ApplicationField | None = None,
        listener: ApplicationField | None = None,
    ) -> BehaviorResult:
        """Validate configuration with the same form used by the editor.

        Field eligibility and permissions must also be checked by the caller;
        get_listener_fields and get_target_fields describe eligibility;
        they do not grant authorization.
        """
        if self.requires_target_field and not context.target_field:
            raise forms.ValidationError("Select a target field for this action.")
        from bloomerp.form_behaviors.utils import clean_action_config

        return self.execute(
            context, clean_action_config(self, listener, target, config or {})
        )


# Persisted declarations contain data only, never executable definitions.


class BehaviorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    target_field: str | None = Field(default=None, min_length=1)
    config: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value: Any) -> Any:
        """Store definition references as stable action IDs."""
        return value.id if isinstance(value, BehaviorActionDefinition) else value


class FormBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = ""
    enabled: bool = True
    events: list[Literal["initial", "change"]] = Field(
        default_factory=lambda: ["change"],
        min_length=1,
    )
    conditions: list[Filter] = Field(default_factory=list)
    actions: list[BehaviorAction] = Field(min_length=1)


class BehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    behaviors: list[FormBehavior] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_behavior_ids(self) -> BehaviorConfig:
        """Reject duplicate identifiers within one listener configuration."""
        ids = [behavior.id for behavior in self.behaviors]
        if len(ids) != len(set(ids)):
            raise ValueError("Behavior IDs must be unique within a field.")
        return self

    def to_storage(self) -> dict[str, Any]:
        """Serialize declarations into JSON-compatible preference data."""
        return self.model_dump(mode="json")
