"""Filter object label membership through content-type-scoped existence queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import CharField, Exists, OuterRef, Q, UUIDField
from django.db.models.functions import Cast
from django.utils.html import format_html_join

from bloomerp.field_types.builtins.display import standard_display_options
from bloomerp.field_types.builtins.other import CanonicalUUIDText
from bloomerp.field_types.registry import FieldTypeDefinition, FieldTypeRegistry
from bloomerp.lookups import builtins as lookups
from bloomerp.lookups.builtins.utils import is_truthy, list_value
from bloomerp.lookups.definition import BoundLookup, CompiledLookup, FilterFieldContext
from bloomerp.model_fields.labels_field import BloomerpLabelsField

if TYPE_CHECKING:
    from django.db.models import Model

    from bloomerp.models.application_field import ApplicationField


def label_ids(value: Any) -> set[str]:
    """Normalize labels and serialized identifiers for membership comparisons."""
    return {str(getattr(item, "pk", item)) for item in list_value(value)}


def labels_q_factory(
    application_field: ApplicationField, field_path: str, expression: str, value: Any
) -> CompiledLookup:
    """Use EXISTS so label filters never multiply parent rows or cross model boundaries."""
    from bloomerp.models.communication.object_label import ObjectLabel

    prefix, _, _ = field_path.rpartition("__")
    owner = OuterRef(f"{prefix}__pk" if prefix else "pk")
    owner = (
        CanonicalUUIDText(owner)
        if isinstance(application_field.get_model()._meta.pk, UUIDField)
        else Cast(owner, CharField())
    )
    assignments = ObjectLabel.objects.filter(
        content_type_id=application_field.content_type_id, object_id=owner
    )
    if expression in {"is_null", "isnull"}:
        return CompiledLookup(
            predicate=Q(
                ~Exists(assignments) if is_truthy(value) else Exists(assignments)
            )
        )
    assignments = assignments.filter(label_id__in=label_ids(value))
    exists = Exists(assignments)
    return CompiledLookup(
        predicate=Q(~exists if expression in {"not_equals", "ne"} else exists)
    )


def single_label_form(context: FilterFieldContext) -> forms.ModelChoiceField:
    """Offer the shared label catalogue as a single filter selection."""
    from bloomerp.models.communication.label import Label

    return forms.ModelChoiceField(queryset=Label.objects.order_by("name", "pk"))


def multiple_labels_form(context: FilterFieldContext) -> forms.ModelMultipleChoiceField:
    """Offer multiple labels with any-of membership semantics."""
    from bloomerp.models.communication.label import Label

    return forms.ModelMultipleChoiceField(
        queryset=Label.objects.order_by("name", "pk"), required=False
    )


def has_labels(actual: Any, expected: Any) -> bool:
    """Match a record containing at least one selected label."""
    return bool(label_ids(actual) & label_ids(expected))


def lacks_label(actual: Any, expected: Any) -> bool:
    """Include unlabeled objects when excluding a selected label."""
    return not has_labels(actual, expected)


def labels_are_empty(actual: Any, expected: Any) -> bool:
    """Keep empty-label checks consistent between Python and database evaluation."""
    return (not label_ids(actual)) == is_truthy(expected)


def render_labels(application_field: ApplicationField, instance: Model) -> str:
    """Render escaped label names when the virtual field is selected in a dataview."""
    return format_html_join(
        " ",
        '<span class="badge badge-secondary">{}</span>',
        ((label.name,) for label in getattr(instance, application_field.field)),
    )


LABELS_FIELD = FieldTypeDefinition(
    id="BloomerpLabelsField",
    label="Labels",
    icon="fa-solid fa-tags",
    model_field_cls=BloomerpLabelsField,
    lookups=(
        BoundLookup(
            lookups.EQUALS,
            q_factory=labels_q_factory,
            form_factory=single_label_form,
            python_evaluator=has_labels,
        ),
        BoundLookup(
            lookups.NOT_EQUALS,
            q_factory=labels_q_factory,
            form_factory=single_label_form,
            python_evaluator=lacks_label,
        ),
        BoundLookup(
            lookups.VALUES_IN,
            q_factory=labels_q_factory,
            form_factory=multiple_labels_form,
            python_evaluator=has_labels,
        ),
        BoundLookup(
            lookups.IS_NULL,
            q_factory=labels_q_factory,
            python_evaluator=labels_are_empty,
        ),
    ),
    render_value=render_labels,
    display_options=standard_display_options,
)


def register(registry: FieldTypeRegistry) -> None:
    """Expose label membership operators to application-field discovery."""
    registry.register("LABELS_FIELD", LABELS_FIELD)
