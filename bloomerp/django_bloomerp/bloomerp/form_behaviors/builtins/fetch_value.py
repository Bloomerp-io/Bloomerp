"""Fetch a value from an authorized record selected by draft-aware filters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Model
from django.http import HttpRequest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from bloomerp.filters.definition import Filter, Filters
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.form_behaviors.builtins.set_o2m_value import compatible_columns
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.widgets.filter_widget import FilterWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

FILTERS_ADAPTER = TypeAdapter(list[Filter])
VALUE_REFERENCE = re.compile(
    r"^\s*\{\{\s*(object|row)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$"
)


def _content_type_from_initial(value: Any) -> ContentType | None:
    """Resolve a partially configured content-type value without raising."""
    if isinstance(value, ContentType):
        return value
    try:
        return ContentType.objects.filter(pk=value).first()
    except (TypeError, ValueError):
        return None


def parse_filters(value: Any) -> Filters:
    """Validate JSON configuration against the unified filter schema."""
    if value in (None, "", []):
        return []
    try:
        return FILTERS_ADAPTER.validate_python(value)
    except PydanticValidationError as error:
        raise forms.ValidationError("Select valid matching filters.") from error


def resolve_filter_values(
    filters: Filters,
    *,
    object_values: Mapping[str, Any],
    row_values: Mapping[str, Any] | None = None,
) -> Filters:
    """Replace exact object/row references while preserving each value's native type."""
    resolved: list[Filter] = []
    sources = {"object": object_values, "row": row_values or {}}
    for group in filters:
        conditions = []
        for condition in group.conditions:
            value = condition.value
            match = VALUE_REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if match is not None:
                source_name, field_name = match.groups()
                source = sources[source_name]
                if field_name not in source:
                    raise forms.ValidationError(
                        f"The filter references unavailable {source_name} field '{field_name}'."
                    )
                value = source[field_name]
            conditions.append(condition.model_copy(update={"value": value}))
        resolved.append(group.model_copy(update={"conditions": conditions}))
    return resolved


def filter_value_references(filters: Filters) -> set[tuple[str, str]]:
    """Return object/row fields referenced by exact filter value placeholders."""
    references: set[tuple[str, str]] = set()
    for group in filters:
        for condition in group.conditions:
            value = condition.value
            match = VALUE_REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if match is not None:
                references.add((match.group(1), match.group(2)))
    return references


def resolve_behavior_field_references(
    filters: Filters,
    *,
    object_model: type[Model],
    row_model: type[Model] | None = None,
) -> tuple[BehaviorFieldReference, ...]:
    """Resolve placeholder dependencies so the executor loads and authorizes them."""
    references: list[BehaviorFieldReference] = []
    for scope, field_name in sorted(filter_value_references(filters)):
        model = object_model if scope == "object" else row_model
        field = (
            ApplicationField.get_for_model(model).filter(field=field_name).first()
            if model is not None
            else None
        )
        if field is None:
            raise forms.ValidationError(
                f"The filter references unknown {scope} field '{field_name}'."
            )
        references.append(BehaviorFieldReference(field=field))
    return tuple(references)


def fetch_matching_value(
    *,
    content_type: ContentType,
    fetch_field: ApplicationField,
    filters: Filters,
    strategy: str,
    user: BehaviorUser,
) -> tuple[bool, Any] | BehaviorResult:
    """Return one authorized field value, or a permission-denied behavior result."""
    model = content_type.model_class()
    if model is None or fetch_field.content_type_id != content_type.pk:
        raise forms.ValidationError("The configured source model is unavailable.")
    manager = UserPolicyManager(user)
    try:
        if not manager.has_field_permission(fetch_field, "view"):
            raise PermissionDenied
        manager.validate_filters(model, filters)
        queryset = manager.get_accessible_queryset(model, "view")
        queryset = (
            ModelFilterManager(model).apply(filters, queryset=queryset)
            if filters
            else queryset
        )
    except PermissionDenied:
        return permission_denied_result("you cannot read the configured lookup data")
    direction = "-" if strategy == "last" else ""
    record = queryset.order_by(f"{direction}{model._meta.pk.name}").first()
    if record is None:
        return False, None
    if (
        not manager.get_accessible_fields_for_object(record, "view")
        .filter(pk=fetch_field.pk)
        .exists()
    ):
        return permission_denied_result("you cannot read the configured lookup data")
    value = getattr(record, fetch_field.field)
    if isinstance(value, Model):
        value = value.pk
    return True, serialize_form_value(value)


def fetch_value_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build a source-model lookup form whose value field matches the target."""
    if target is None:
        raise forms.ValidationError("Select a target field first.")

    class FetchValueForm(forms.Form):
        """Configure which record and source field supply the target value."""

        refresh_fields = ("fetch_from",)
        fetch_from = forms.ModelChoiceField(
            queryset=ContentType.objects.all(),
            label="Source model",
            widget=ForeignFieldWidget(
                model=ContentType, attrs={"class": "input w-full"}
            ),
        )
        filters = forms.JSONField(
            required=False,
            label="Matching records",
            widget=forms.HiddenInput(),
            help_text="Filter the source model. Values may use {{ object.field }}.",
        )
        fetch_field = forms.ModelChoiceField(
            queryset=ApplicationField.objects.none(),
            label="Value field",
        )
        fetch_strategy = forms.ChoiceField(
            label="When several records match",
            choices=(("first", "Use first record"), ("last", "Use last record")),
        )

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Scope the filter widget and value choices to the selected source model."""
            super().__init__(*args, **kwargs)
            content_type = _content_type_from_initial(self.initial.get("fetch_from"))
            if content_type is None or content_type.model_class() is None:
                return
            model = content_type.model_class()
            self.fields["filters"].widget = FilterWidget(
                model=model, include_controls=False
            )
            self.fields["fetch_field"].queryset = compatible_columns(
                ApplicationField.get_for_model(model), target
            )

        def clean(self) -> dict[str, Any]:
            """Validate filter JSON and expose permission-aware field references."""
            cleaned = super().clean()
            content_type = cleaned.get("fetch_from")
            fetch_field = cleaned.get("fetch_field")
            if content_type is not None and fetch_field is not None:
                if fetch_field.content_type_id != content_type.pk:
                    self.add_error(
                        "fetch_field", "Select a field from the source model."
                    )
                else:
                    cleaned["fetch_field"] = BehaviorFieldReference(field=fetch_field)
            try:
                cleaned["filters"] = parse_filters(cleaned.get("filters"))
                cleaned["value_references"] = resolve_behavior_field_references(
                    cleaned["filters"],
                    object_model=target.get_model(),
                )
            except forms.ValidationError as error:
                self.add_error("filters", error)
            return cleaned

    return FetchValueForm


def fetch_value(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Fetch one matching record's field and place it in the selected target."""
    reference: BehaviorFieldReference = config["fetch_field"]
    filters = resolve_filter_values(config["filters"], object_values=context.values)
    result = fetch_matching_value(
        content_type=config["fetch_from"],
        fetch_field=reference.field,
        filters=filters,
        strategy=config["fetch_strategy"],
        user=user,
    )
    if isinstance(result, BehaviorResult):
        return result
    found, value = result
    if not found or context.target_value == value:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=value),)
    )


FETCH_VALUE = BehaviorActionDefinition(
    id="fetch_value",
    label="Fetch value from a record",
    description=(
        "Find the first or last accessible record matching draft-aware filters, "
        "then copy one of its fields into the selected form field."
    ),
    requires_target_field=True,
    config_form_factory=fetch_value_config_form_factory,
    execute=fetch_value,
    group="Data lookup",
)
