"""Enable or disable interaction with a target field while preserving its value."""

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

Interaction = Literal["enabled", "disabled"]


class SetFieldInteractionForm(forms.Form):
    """Choose whether the target field accepts interaction."""

    interaction = forms.ChoiceField(
        choices=(("enabled", "Enabled"), ("disabled", "Disabled")),
    )


def set_field_interaction_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Return the fixed interaction configuration form."""
    return SetFieldInteractionForm


def set_field_interaction(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Set only the target's disabled state."""
    interaction = cast(Interaction, config["interaction"])
    return BehaviorResult(
        states=(
            FieldStateUpdate(
                field=context.target_field,
                disabled=interaction == "disabled",
            ),
        )
    )


SET_FIELD_INTERACTION = BehaviorActionDefinition(
    id="set_field_interaction",
    label="Set field interaction",
    description="Enable or disable the target field without changing its value or visibility.",
    requires_target_field=True,
    execute=set_field_interaction,
    config_form_factory=set_field_interaction_config_form_factory,
    group="Field state",
)
