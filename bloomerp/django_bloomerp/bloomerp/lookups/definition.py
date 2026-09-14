from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Type

from django import forms
from django.db.models import Expression, Q, Model




if TYPE_CHECKING:
    from bloomerp.field_types.registry import FieldTypeDefinition
    from bloomerp.filters.definition import FilterField
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.filters.definition import FilterFieldGroup

LookupExpression = str
LookupValue = Any
FieldPath = str


@dataclass(frozen=True)
class CompiledLookup:
    """The Django ORM result of compiling one lookup condition."""

    predicate: Q
    annotations: Mapping[str, Expression] = field(default_factory=dict)
    distinct: bool = False


@dataclass(frozen=True)
class CompiledSQL:
    """A parameterized SQL fragment produced for one lookup condition."""

    clause: str
    parameters: tuple[Any, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SQLLookupContext:
    """Runtime metadata for compiling a lookup against a validated SQL field."""

    field_path: FieldPath
    sql_type: str | None = None
    nullable: bool | None = None
    dialect: str = "postgres"


QFactory = Callable[
    ["ApplicationField", FieldPath, LookupExpression, LookupValue],
    CompiledLookup,
]
SQLFactory = Callable[
    [SQLLookupContext, LookupExpression, LookupValue],
    CompiledSQL,
]
PythonEvaluator = Callable[[Any, Any], bool]


@dataclass(frozen=True, kw_only=True)
class FilterFieldContext:
    """Resolved metadata for a model or analytics lookup value editor.

    Model/dataview fields retain their application field. Analytics fields use
    the field type's standalone form and widget factories.
    This context is internal metadata, not the serialized filter payload.
    """
    field_type: FieldTypeDefinition
    application_field: ApplicationField | None = None

    def get_form_field(self) -> forms.Field:
        """Build a fresh default editor; lookup-specific factories may override it."""
        if self.application_field is not None:
            form_field = self.application_field.get_form_field()
            if form_field is not None:
                return form_field
        
        from bloomerp.field_types.registry import FieldContext

        context = FieldContext(attrs={"class": "input w-full"})
        factory = self.field_type.form_factory
        form_field = factory(context, None) if factory else None
        if form_field is None:
            form_field = forms.CharField()
        if self.field_type.widget_factory is not None:
            form_field.widget = self.field_type.widget_factory(context)
        else:
            form_field.widget.attrs.update(context.attrs)
        return form_field



LookupFormFactory = Callable[[FilterFieldContext], forms.Field]


def default_q_factory(
    application_field: ApplicationField,
    field_path: FieldPath,
    expression: LookupExpression,
    value: LookupValue,
) -> CompiledLookup:
    """Compile a lookup whose expression is already a Django ORM expression."""

    resolved_path = "__".join(part for part in (field_path, expression) if part)
    return CompiledLookup(predicate=Q(**{resolved_path: value}))


@dataclass(frozen=True)
class LookupDefinition:
    """Field-independent defaults for a lookup operator."""

    id: str
    label: str
    expressions: tuple[LookupExpression, ...]
    description: str | None = None
    nested: bool = False

    q_factory: QFactory | None = None
    sql_factory: SQLFactory | None = None
    python_evaluator: PythonEvaluator | None = None
    default_form_factory: LookupFormFactory | None = None
    nested_fields_factory: Callable[[Type[Model], FieldPath], list[FilterFieldGroup]] | None = None
    
    def __post_init__(self) -> None:
        object.__setattr__(self, "expressions", tuple(self.expressions))

        if not self.id:
            raise ValueError("A lookup requires a non-empty ID.")
        if not self.expressions and not self.nested:
            raise ValueError(
                "A non-nested lookup requires at least one expression."
            )
        if self.nested:
            if any(factory is not None for factory in (
                self.q_factory, self.sql_factory, self.python_evaluator,
            )):
                raise ValueError("Nested lookups delegate execution to a terminal lookup.")
        elif self.q_factory is None:
            object.__setattr__(self, "q_factory", default_q_factory)


@dataclass(frozen=True)
class BoundLookup:
    """Field-type-specific overrides for a registered lookup definition."""

    lookup: LookupDefinition
    form_factory: LookupFormFactory | None = None
    q_factory: QFactory | None = None
    sql_factory: SQLFactory | None = None
    python_evaluator: PythonEvaluator | None = None

    def __post_init__(self) -> None:
        if self.lookup.nested and any(factory is not None for factory in (
            self.q_factory, self.sql_factory, self.python_evaluator,
        )):
            raise ValueError("Nested lookups cannot override execution factories.")

    @property
    def id(self) -> str:
        return self.lookup.id

    @property
    def label(self) -> str:
        return self.lookup.label

    @property
    def description(self) -> str | None:
        return self.lookup.description

    @property
    def expressions(self) -> tuple[LookupExpression, ...]:
        return self.lookup.expressions

    @property
    def nested(self) -> bool:
        return self.lookup.nested

    def get_q_factory(self) -> QFactory | None:
        return self.q_factory or self.lookup.q_factory

    def get_sql_factory(self) -> SQLFactory | None:
        return self.sql_factory or self.lookup.sql_factory

    def get_python_evaluator(self) -> PythonEvaluator | None:
        return self.python_evaluator or self.lookup.python_evaluator

    def get_form_factory(
        self,
        field_type_default: LookupFormFactory | None = None,
    ) -> LookupFormFactory | None:
        return (
            self.form_factory
            or self.lookup.default_form_factory
            or field_type_default
        )

    @classmethod
    def normalize(cls, lookup: LookupDefinition | BoundLookup) -> BoundLookup:
        """Return a uniform bound representation for registry consumers."""

        return lookup if isinstance(lookup, cls) else cls(lookup=lookup)


Lookup = LookupDefinition | BoundLookup
    
