"""Set a target field's visibility without changing its value or interaction state."""

from typing import Literal, cast

from django import forms
from django.http import HttpRequest

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
)
from bloomerp.models.application_field import ApplicationField

Visibility = Literal["visible", "hidden"]


class SetFieldVisibilityForm(forms.Form):
    """Choose whether the target field is visible or hidden."""

    visibility = forms.ChoiceField(
        choices=(("visible", "Visible"), ("hidden", "Hidden")),
    )


def set_field_visibility_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Return the fixed visibility configuration form."""
    return SetFieldVisibilityForm


def set_field_visibility(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Set only the target's visibility state."""
    visibility = cast(Visibility, config["visibility"])
    return BehaviorResult(
        states=(
            FieldStateUpdate(
                field=context.target_field,
                visible=visibility == "visible",
            ),
        )
    )


SET_FIELD_VISIBILITY = BehaviorActionDefinition(
    id="set_field_visibility",
    label="Set field visibility",
    description="Show or hide the target field without changing its value or interaction state.",
    requires_target_field=True,
    execute=set_field_visibility,
    config_form_factory=set_field_visibility_config_form_factory,
    group="Field state",
)
