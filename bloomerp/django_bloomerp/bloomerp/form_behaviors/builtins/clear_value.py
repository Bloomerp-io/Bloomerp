"""Clear a target using its registered public empty-value contract."""

from copy import deepcopy
from typing import Any

from django import forms
from django.http import HttpRequest

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldValueUpdate,
)
from bloomerp.form_fields.structured_value import serialize_form_value
from bloomerp.models.application_field import ApplicationField


def public_empty_value(target: ApplicationField) -> Any:
    """Return the target validator's JSON-compatible representation of empty input."""
    form_field = target.get_form_field()
    if form_field is None:
        raise forms.ValidationError(
            f"Field '{target.field}' has no editable value contract."
        )
    form_field.required = False
    return serialize_form_value(form_field.clean(None))


def clear_value_config_form_factory(
    target: ApplicationField | None, listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build an empty form that derives the selected target's public empty value."""
    if target is None:
        raise forms.ValidationError("Select a target field first.")
    empty_value = public_empty_value(target)

    class ClearValueForm(forms.Form):
        """Supply a validated, target-specific empty value to the action."""

        def clean(self) -> dict[str, Any]:
            """Attach the derived empty value without adding persisted configuration."""
            cleaned = super().clean()
            cleaned["empty_value"] = deepcopy(empty_value)
            return cleaned

    return ClearValueForm


def clear_value(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Replace only the declared target with its validated public empty value."""
    return BehaviorResult(
        values=(
            FieldValueUpdate(
                field=context.target_field,
                value=deepcopy(config["empty_value"]),
            ),
        )
    )


CLEAR_VALUE = BehaviorActionDefinition(
    id="clear_value",
    label="Clear value",
    description="Clear the target using its field type's empty-value semantics.",
    requires_target_field=True,
    execute=clear_value,
    config_form_factory=clear_value_config_form_factory,
)
