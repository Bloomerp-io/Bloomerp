"""Field type definitions, factories, and the extensible registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable, TYPE_CHECKING, Any
from bloomerp.field_types.display_options import FieldDisplayOption
from bloomerp.field_types.construction import FieldConstructionOption
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.utils.registry import BaseRegistry
from dataclasses import dataclass, field
from django import forms
from django.db import models

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


@dataclass(frozen=True, kw_only=True)
class FieldContext:
    application_field: ApplicationField | None = None
    attrs: Mapping[str, Any] = field(default_factory=dict)
    layout_config: Mapping[str, Any] = field(default_factory=dict)


WidgetFactory = Callable[[FieldContext], forms.Widget]

FormFactory = Callable[[FieldContext, forms.Field | None], forms.Field | None]

ValueRenderer = Callable[["ApplicationField", models.Model], Any]


@dataclass(frozen=True, kw_only=True)
class FieldConstruction:
    """Configuration for module generation and the model builder."""

    defaults: Mapping[str, Any] = field(default_factory=dict)
    options: tuple[FieldConstructionOption, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "options", tuple(self.options))



@dataclass(frozen=True, kw_only=True)
class FieldTypeDefinition:
    id: str
    label: str
    description: str | None = None
    icon: str = "fa-solid fa-table-columns"

    model_field_cls: type[models.Field] | None = None
    construction: FieldConstruction | None = None

    widget_factory: WidgetFactory | None = None
    form_factory: FormFactory | None = None
    render_value: ValueRenderer = lambda application_field, instance: getattr(
        instance, application_field.field, None
    )

    lookups: tuple[LookupDefinition, ...] = ()
    display_options: tuple[FieldDisplayOption, ...] = ()
    
    
    @property
    def allow_in_model(self) -> bool:
        """Whether this type supplies a Django field class for model declarations.

        True means ``model_field_cls`` can be used to declare a field on a
        Django model, given the required constructor arguments. False means
        this definition has no model field class, as with properties and
        reverse relations. Construction metadata is optional and does not
        determine this capability.

        This does not indicate whether a particular field is editable, belongs
        in ModelForm.Meta.fields, or is offered by the model builder. Those
        decisions depend on the actual model field and the consuming feature.
        A type without a model field class can still provide an editable
        virtual form field through its form_factory.
        """
        return self.model_field_cls is not None

    def get_lookup_by_id(self, lookup_id: str) -> LookupDefinition | None:
        for lookup in self.lookups:
            if lookup.id == lookup_id:
                return lookup
        return None

    def __post_init__(self):
        object.__setattr__(self, "lookups", tuple(self.lookups))
        object.__setattr__(self, "display_options", tuple(self.display_options))


class FieldTypeRegistry(BaseRegistry[FieldTypeDefinition]):
    def _ensure_loaded(self) -> None:
        # Raw-module imports and public-package imports must behave identically.
        # Independently constructed registries remain empty until registered into.
        if self is globals().get("FIELD_TYPE_REGISTRY") and not _builtins_loading:
            load_builtin_field_types()

    def __getattr__(self, key: str) -> FieldTypeDefinition:
        self._ensure_loaded()
        return super().__getattr__(key)

    def get(self, key: str) -> FieldTypeDefinition | None:
        self._ensure_loaded()
        return super().get(key)

    def values(self) -> list[FieldTypeDefinition]:
        self._ensure_loaded()
        return super().values()

    def register(self, key: str, obj: FieldTypeDefinition) -> None:
        if isinstance(obj, FieldTypeDefinition) and any(
            item.id == obj.id for item in self.values()
        ):
            raise ValueError(f"Field type ID {obj.id!r} is already registered")
        super().register(key, obj)

    def from_id(self, field_id: str) -> FieldTypeDefinition:
        for definition in self.values():
            if definition.id == field_id:
                return definition
        raise ValueError(f"Unknown field type: {field_id}")

    def resolve(self, field_id: str, model_field=None) -> FieldTypeDefinition:
        """Preserve declared variants while recognizing specific Django subclasses."""
        try:
            declared = self.from_id(field_id)
        except ValueError:
            declared = None

        # Walk from the actual class toward its bases, matching legacy resolution.
        inferred = None
        if model_field is not None:
            for candidate in type(model_field).__mro__:
                inferred = next(
                    (
                        item
                        for item in self.values()
                        if item.model_field_cls is candidate
                    ),
                    None,
                )
                if inferred is not None:
                    break

            # A specific model class overrides a stale generic declaration.
            if (
                inferred is not None
                and inferred.model_field_cls is type(model_field)
                and (
                    declared is None
                    or declared.model_field_cls is not type(model_field)
                )
            ):
                return inferred

        # Preserve intentional variants sharing a Django class, such as ChoiceField.
        if declared is not None:
            return declared
        if inferred is not None:
            return inferred
        raise ValueError(f"Unknown field type: {field_id}")

    def get_from_model_field_cls(self, model_field_cls) -> FieldTypeDefinition | None:
        """Find the most specific registered class, or allow the caller to fall back."""
        for candidate in model_field_cls.__mro__:
            for definition in self.values():
                if definition.model_field_cls is candidate:
                    return definition
        return None

    def choices(self) -> list[tuple[str, str]]:
        return [(definition.id, definition.label) for definition in self.values()]

    def items(self) -> list[tuple[str, FieldTypeDefinition]]:
        """Return symbolic keys and definitions in registration order."""
        self._ensure_loaded()
        return list(self._registry.items())

    def template_context(
        self, field_type: FieldTypeDefinition | str | None
    ) -> dict[str, bool]:
        """Preserve the template flags previously derived from enum member names."""
        field_id = (
            field_type.id if isinstance(field_type, FieldTypeDefinition) else field_type
        )
        return {
            key.lower(): definition.id == field_id for key, definition in self.items()
        }


FIELD_TYPE_REGISTRY = FieldTypeRegistry(FieldTypeDefinition)


_builtins_loaded = False
_builtins_loading = False


def load_builtin_field_types() -> FieldTypeRegistry:
    """Populate the global registry once; legacy enum consumers stay independent."""
    global _builtins_loaded, _builtins_loading
    if not _builtins_loaded and not _builtins_loading:
        from bloomerp.field_types.builtins import register_builtin_field_types

        _builtins_loading = True
        original = FIELD_TYPE_REGISTRY._registry.copy()
        try:
            register_builtin_field_types(FIELD_TYPE_REGISTRY)
            _builtins_loaded = True
        except Exception:
            # A failed import must not leave a partially registered catalog.
            FIELD_TYPE_REGISTRY._registry = original
            raise
        finally:
            _builtins_loading = False
    return FIELD_TYPE_REGISTRY


def field_type_choices() -> list[tuple[str, str]]:
    """Resolve choices lazily, after Django models and extension apps are loaded."""
    return load_builtin_field_types().choices()
