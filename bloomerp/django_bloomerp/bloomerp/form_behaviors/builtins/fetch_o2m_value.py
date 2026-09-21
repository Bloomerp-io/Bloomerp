"""Populate a one-to-many row column from authorized record lookups."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.http import HttpRequest

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.fetch_value import (
    _content_type_from_initial,
    fetch_matching_value,
    parse_filters,
    resolve_behavior_field_references,
    resolve_filter_values,
)
from bloomerp.form_behaviors.builtins.set_o2m_value import (
    collection_rows,
    compatible_columns,
    value_columns,
)
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorFieldReference,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.filter_widget import FilterWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


def rendered_value_columns(
    listener: ApplicationField,
) -> QuerySet[ApplicationField]:
    """Return editable value columns rendered by the listener's configured widget."""
    layout_config = getattr(listener, "_behavior_layout_config", {})
    widget = listener.get_widget(layout_config=layout_config)
    rendered_ids = [column.pk for column in widget.get_columns()]
    return value_columns(listener.get_related_model()).filter(pk__in=rendered_ids)


def fetch_o2m_value_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build a lookup form for a destination column in the listener's child rows."""
    if listener is None or listener.get_related_model() is None:
        raise forms.ValidationError("Select a one-to-many listener first.")
    columns = rendered_value_columns(listener)

    class FetchO2MValueForm(forms.Form):
        """Configure a per-row lookup and its destination child column."""

        refresh_fields = ("target_column", "fetch_from")
        target_column = forms.ModelChoiceField(
            queryset=columns,
            label="Destination column",
        )
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
            help_text=(
                "Filter the source model. Values may use {{ row.column }} "
                "or {{ object.field }}."
            ),
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
            """Rebuild compatible source choices from partial editor configuration."""
            super().__init__(*args, **kwargs)
            target_value = self.initial.get("target_column")
            target_column = (
                target_value
                if isinstance(target_value, ApplicationField)
                else columns.filter(field=str(target_value or "")).first()
            )
            content_type = _content_type_from_initial(self.initial.get("fetch_from"))
            if content_type is None or content_type.model_class() is None:
                return
            model = content_type.model_class()
            self.fields["filters"].widget = FilterWidget(
                model=model, include_controls=False
            )
            candidates = ApplicationField.get_for_model(model)
            if target_column is not None:
                candidates = compatible_columns(candidates, target_column)
            self.fields["fetch_field"].queryset = candidates

        def clean(self) -> dict[str, Any]:
            """Validate lookup filters and mark source/destination permissions."""
            cleaned = super().clean()
            content_type = cleaned.get("fetch_from")
            target_column = cleaned.get("target_column")
            fetch_field = cleaned.get("fetch_field")
            if content_type is not None and fetch_field is not None:
                if fetch_field.content_type_id != content_type.pk:
                    self.add_error(
                        "fetch_field", "Select a field from the source model."
                    )
                else:
                    cleaned["fetch_field"] = BehaviorFieldReference(field=fetch_field)
            if target_column is not None:
                cleaned["target_column"] = BehaviorFieldReference(
                    field=target_column,
                    permission="change",
                )
            try:
                cleaned["filters"] = parse_filters(cleaned.get("filters"))
                cleaned["value_references"] = resolve_behavior_field_references(
                    cleaned["filters"],
                    object_model=listener.get_model(),
                    row_model=listener.get_related_model(),
                    allowed_row_fields=columns,
                )
            except forms.ValidationError as error:
                self.add_error("filters", error)
            return cleaned

    return FetchO2MValueForm


def fetch_o2m_value(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Run the configured lookup for each active row and update its destination."""
    rows = collection_rows(context.listener_value)
    if not rows:
        return BehaviorResult()
    target_reference: BehaviorFieldReference = config["target_column"]
    fetch_reference: BehaviorFieldReference = config["fetch_field"]
    changed = False
    for row in rows:
        if row.get("DELETE") in (True, "true", "True", "1", "on", "yes"):
            continue
        filters = resolve_filter_values(
            config["filters"],
            object_values=context.values,
            row_values=row,
        )
        result = fetch_matching_value(
            content_type=config["fetch_from"],
            fetch_field=fetch_reference.field,
            filters=filters,
            strategy=config["fetch_strategy"],
            user=user,
        )
        if isinstance(result, BehaviorResult):
            return result
        found, value = result
        if found and row.get(target_reference.field.field) != value:
            row[target_reference.field.field] = value
            changed = True
    if not changed:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.listener_field, value=rows),)
    )


def fetch_o2m_listener_fields(
    fields: QuerySet[ApplicationField],
) -> QuerySet[ApplicationField]:
    """Limit the action to one-to-many listener fields."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id)


FETCH_O2M_VALUE = BehaviorActionDefinition(
    id="fetch_o2m_value",
    label="Fetch values into one-to-many rows",
    description=(
        "For every active child row, find the first or last accessible record "
        "matching row-aware filters and copy one field into a destination column."
    ),
    config_form_factory=fetch_o2m_value_config_form_factory,
    requires_target_field=False,
    get_listener_fields=fetch_o2m_listener_fields,
    execute=fetch_o2m_value,
    group="Data lookup",
)
