"""Copy row values or a related record's field into a collection column."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django import forms
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db.models import Model, QuerySet
from django.http import HttpRequest

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager


def collection_rows(value: Any) -> list[dict[str, Any]]:
    """Copy a collection draft so actions never mutate the caller's rows."""
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise forms.ValidationError("Expected a list of row dictionaries.")
    return deepcopy(value)


def value_columns(model: type[Model]) -> QuerySet[ApplicationField]:
    """Offer editable scalar columns and single-record relations, excluding identities."""
    eligible: list[int] = []
    fields = ApplicationField.get_for_model(model)
    for field in fields:
        try:
            model_field = model._meta.get_field(field.field)
        except FieldDoesNotExist:
            continue
        if (
            model_field.concrete
            and not model_field.primary_key
            and not model_field.many_to_many
            and model_field.editable
            and field.get_form_field() is not None
        ):
            eligible.append(field.pk)
    return fields.filter(pk__in=eligible)


def compatible_columns(
    fields: QuerySet[ApplicationField],
    target: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Match the existing copy-value type contract and preserve relation identity types."""
    if target is None:
        return fields
    return fields.filter(
        field_type=target.field_type, related_model_id=target.related_model_id
    )


def config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Return a form class whose choices depend on its current initial configuration."""
    if target is None or target.get_related_model() is None:
        raise forms.ValidationError("Select a collection target first.")
    columns = value_columns(target.get_related_model()).exclude(
        field=target._get_model_field().field.name,
    )

    class SetO2MValueForm(forms.Form):
        """Select a destination, source column, and optional related-record accessor."""

        refresh_fields = ("from_column", "to_column")

        from_column = forms.ModelChoiceField(queryset=columns, label="From column")
        to_column = forms.ModelChoiceField(queryset=columns, label="To column")
        accessor = forms.ModelChoiceField(
            queryset=ApplicationField.objects.none(),
            required=False,
            help_text="Optional field on the selected related record, for example sales_price.",
        )
        write_policy = WritePolicyField(
            allowed=("always", "if_empty_or_zero"),
            default="always",
        )

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Rebuild dependent choices from partial configuration before validation."""
            super().__init__(*args, **kwargs)
            target_column = columns.filter(
                field=self.initial.get("to_column", "")
            ).first()
            source_ids = set(
                compatible_columns(columns, target_column).values_list("pk", flat=True)
            )
            for column in columns.filter(related_model__isnull=False):
                if compatible_columns(
                    value_columns(column.get_related_model()), target_column
                ).exists():
                    source_ids.add(column.pk)
            self.fields["from_column"].queryset = columns.filter(pk__in=source_ids)
            source_column = (
                self.fields["from_column"]
                .queryset.filter(
                    field=self.initial.get("from_column", ""),
                )
                .first()
            )
            if (
                source_column is not None
                and source_column.get_related_model() is not None
            ):
                self.fields["accessor"].queryset = compatible_columns(
                    value_columns(source_column.get_related_model()),
                    target_column,
                )
            else:
                self.fields["accessor"].widget = forms.HiddenInput()
                # Drop obsolete editor state; bound validation still rejects a forged accessor.
                self.initial["accessor"] = None

        def clean(self) -> dict[str, Any]:
            """Reject incompatible direct copies and require an accessor when needed."""
            cleaned = super().clean()
            source = cleaned.get("from_column")
            destination = cleaned.get("to_column")
            accessor = cleaned.get("accessor")
            if source is not None and destination is not None:
                effective_source = accessor or source
                if not compatible_columns(
                    ApplicationField.objects.filter(pk=effective_source.pk),
                    destination,
                ).exists():
                    self.add_error(
                        "accessor",
                        "Select a related field compatible with the target column.",
                    )
            return cleaned

    return SetO2MValueForm


def collection_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Limit this action to fields exposing the collection row value schema."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id)


def resolve_related_values(
    source: ApplicationField,
    accessor: ApplicationField,
    identities: tuple[Any, ...],
    user: BehaviorUser,
) -> Mapping[str, Any]:
    """Read one related column after authorizing its model, rows, and field."""
    model = source.get_related_model()
    if model is None or accessor.get_model() is not model:
        raise forms.ValidationError(
            "Accessor must belong to the source relation's model."
        )
    manager = UserPolicyManager(user)
    if not manager.has_global_permission(model, "view"):
        raise PermissionDenied
    records = list(
        manager.get_accessible_queryset(model, "view").filter(pk__in=identities)
    )
    if {str(record.pk) for record in records} != {
        str(identity) for identity in identities
    }:
        raise PermissionDenied("A related source record is unavailable.")
    model_field = model._meta.get_field(accessor.field)
    if not model_field.concrete or model_field.many_to_many:
        raise forms.ValidationError("Accessor must expose a single stored value.")
    values: dict[str, Any] = {}
    for record in records:
        if (
            not manager.get_accessible_fields_for_object(record, "view")
            .filter(pk=accessor.pk)
            .exists()
        ):
            raise PermissionDenied("The related source field is unavailable.")
        values[str(record.pk)] = getattr(record, model_field.attname)
    return values


def set_o2m_value(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Copy each active row's source, optionally resolving related values in one batch."""
    source: ApplicationField = config["from_column"]
    destination: ApplicationField = config["to_column"]
    accessor: ApplicationField | None = config.get("accessor")
    write_policy: str = config["write_policy"]
    rows = collection_rows(context.target_value)

    active = [
        row
        for row in rows
        if row.get("DELETE") not in (True, "true", "True", "1", "on", "yes")
    ]
    related_values: dict[str, Any] = {}
    if accessor is not None:
        identities = tuple(
            row[source.field]
            for row in active
            if row.get(source.field) not in (None, "")
        )
        if identities:
            try:
                resolver = context.resolve_related_values
                related_values = dict(
                    resolver(source, accessor, identities)
                    if resolver is not None
                    else resolve_related_values(source, accessor, identities, user)
                )
            except PermissionDenied:
                return permission_denied_result(
                    "you cannot read the configured related data"
                )
    changed = False
    for row in active:
        if source.field not in row:
            continue
        value = row[source.field]
        if accessor is not None:
            if value in (None, ""):
                continue
            if str(value) not in related_values:
                raise forms.ValidationError("A related source value is unavailable.")
            value = related_values[str(value)]

        should_write = should_write_value(
            row.get(destination.field), write_policy, field=destination
        )

        if row.get(destination.field) != value and should_write:
            row[destination.field] = deepcopy(value)
            changed = True
    return (
        BehaviorResult(
            values=(FieldValueUpdate(field=context.target_field, value=rows),)
        )
        if changed
        else BehaviorResult()
    )


SET_O2M_VALUE = BehaviorActionDefinition(
    id="set_o2m_value",
    label="Set related-row value",
    description="Copy each active row's source column or related accessor into a compatible column.",
    requires_target_field=True,
    execute=set_o2m_value,
    config_form_factory=config_form_factory,
    get_target_fields=collection_targets,
)
