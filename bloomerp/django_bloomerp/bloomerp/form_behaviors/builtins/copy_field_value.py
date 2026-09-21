"""Copy a listener value or one field from its selected related record."""

from copy import deepcopy
from typing import Any, Literal, cast

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_behaviors.builtins.fetch import single_value_fields
from bloomerp.form_behaviors.builtins.set_o2m_value import (
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
from bloomerp.form_behaviors.shared.permissions import permission_denied_result
from bloomerp.form_behaviors.shared.write_policy import (
    WritePolicyField,
    should_write_value,
)
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager

CopySource = Literal["listener", "related_field"]
RELATION_FIELD_TYPES = (
    FIELD_TYPE_REGISTRY.FOREIGN_KEY.id,
    FIELD_TYPE_REGISTRY.ONE_TO_ONE_FIELD.id,
)


def _is_relation_listener(listener: ApplicationField | None) -> bool:
    """Return whether the listener selects exactly one related record."""
    return bool(
        listener is not None
        and listener.field_type in RELATION_FIELD_TYPES
        and listener.get_related_model() is not None
    )


def _related_source_fields(
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Return single-value fields readable from the listener's related model."""
    if not _is_relation_listener(listener):
        return ApplicationField.objects.none()
    related_model = listener.get_related_model() if listener is not None else None
    if related_model is None:
        return ApplicationField.objects.none()
    return single_value_fields(value_columns(related_model))


def copy_field_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Offer targets compatible with the listener or one of its related fields."""
    if listener is None:
        return fields.none()
    eligible_ids = set(
        compatible_columns(fields, listener).values_list("pk", flat=True)
    )
    related_sources = _related_source_fields(listener)
    if related_sources.exists():
        for target in fields:
            if compatible_columns(related_sources, target).exists():
                eligible_ids.add(target.pk)
    return fields.filter(pk__in=eligible_ids)


def copy_field_value_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build direct and related-field source choices for a compatible target."""
    if target is None or listener is None:
        raise forms.ValidationError("Select a listener and target field first.")
    relation_listener = _is_relation_listener(listener)
    direct_compatible = compatible_columns(
        ApplicationField.objects.filter(pk=listener.pk),
        target,
    ).exists()
    related_compatible = relation_listener and compatible_columns(
        _related_source_fields(listener),
        target,
    ).exists()
    if not direct_compatible and not related_compatible:
        raise forms.ValidationError("The listener has no value compatible with the target.")
    default_source = "listener" if direct_compatible else "related_field"
    source_choices: tuple[tuple[str, str], ...] = tuple(
        choice for enabled, choice in (
            (direct_compatible, ("listener", "Listener value")),
            (related_compatible, ("related_field", "Field on selected record")),
        ) if enabled
    )

    class CopyFieldValueForm(forms.Form):
        """Select the direct listener or one compatible related-record field."""

        refresh_fields = ("source",)
        source = forms.ChoiceField(choices=source_choices, initial=default_source)
        related_field = forms.ModelChoiceField(
            queryset=ApplicationField.objects.none(),
            required=False,
        )
        write_policy = WritePolicyField(
            allowed=("always", "if_empty"),
            default="always",
        )

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Expose related choices only when the selected source mode needs them."""
            super().__init__(*args, **kwargs)
            selected_source = self.initial.get("source") or default_source
            if selected_source == "related_field":
                self.fields["related_field"].queryset = compatible_columns(
                    _related_source_fields(listener),
                    target,
                )
            else:
                self.fields["related_field"].widget = forms.HiddenInput()
                self.initial["related_field"] = None

        def clean(self) -> dict[str, Any]:
            """Validate source compatibility and expose permission-aware references."""
            cleaned = super().clean()
            source = cleaned.get("source")
            related_field = cleaned.get("related_field")
            if source == "listener":
                if not compatible_columns(
                    ApplicationField.objects.filter(pk=listener.pk),
                    target,
                ).exists():
                    self.add_error("source", "The listener is incompatible with the target.")
            elif source == "related_field":
                if not relation_listener:
                    self.add_error("source", "The listener does not select a related record.")
                elif related_field is None:
                    self.add_error("related_field", "Select a field from the related record.")
                elif not compatible_columns(
                    _related_source_fields(listener).filter(pk=related_field.pk),
                    target,
                ).exists():
                    self.add_error("related_field", "The related field is incompatible with the target.")
                else:
                    cleaned["related_field"] = BehaviorFieldReference(
                        field=related_field,
                        draft=False,
                    )
            cleaned["listener_field"] = listener
            return cleaned

    return CopyFieldValueForm


def _read_related_value(
    listener: ApplicationField,
    related_field: ApplicationField,
    identity: Any,
    user: BehaviorUser,
) -> tuple[bool, Any] | BehaviorResult:
    """Read one authorized value from the selected related record."""
    related_model = listener.get_related_model()
    if related_model is None or related_field.get_model() is not related_model:
        raise forms.ValidationError("The configured related field is unavailable.")
    manager = UserPolicyManager(user)
    try:
        if (
            not manager.has_global_permission(related_model, "view")
            or not manager.has_field_permission(related_field, "view")
        ):
            raise PermissionDenied
        record = manager.get_accessible_queryset(related_model, "view").filter(
            pk=identity,
        ).first()
    except (TypeError, ValueError, ValidationError, PermissionDenied):
        return permission_denied_result("you cannot read the selected related value")
    if record is None:
        return permission_denied_result("you cannot read the selected related value")
    if not manager.get_accessible_fields_for_object(record, "view").filter(
        pk=related_field.pk,
    ).exists():
        return permission_denied_result("you cannot read the selected related value")
    model_field = related_model._meta.get_field(related_field.field)
    if not model_field.concrete or model_field.many_to_many:
        raise forms.ValidationError("The configured related field is not a stored value.")
    value = getattr(record, model_field.attname)
    return True, serialize_form_value(value)


def copy_field_value(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Copy the configured source into the target without mutating the draft."""
    if not should_write_value(context.target_value, config["write_policy"]):
        return BehaviorResult()
    source = cast(CopySource, config["source"])
    if source == "listener":
        value = deepcopy(serialize_form_value(context.listener_value))
    else:
        if context.listener_value in (None, ""):
            return BehaviorResult()
        listener: ApplicationField = config["listener_field"]
        related_reference: BehaviorFieldReference = config["related_field"]
        result = _read_related_value(
            listener,
            related_reference.field,
            context.listener_value,
            user,
        )
        if isinstance(result, BehaviorResult):
            return result
        _, value = result
    if context.target_value == value:
        return BehaviorResult()
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=value),)
    )


COPY_FIELD_VALUE = BehaviorActionDefinition(
    id="copy_field_value",
    label="Copy field value",
    description="Copy the listener or one field from its selected related record into the target.",
    requires_target_field=True,
    execute=copy_field_value,
    config_form_factory=copy_field_value_config_form_factory,
    get_target_fields=copy_field_targets,
    group="Field values",
)
