"""Return a validated message without requiring a target field."""

from typing import Literal, cast

from django import forms
from django.http import HttpRequest

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorMessage,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
)
from bloomerp.models.application_field import ApplicationField


class MessageConfigForm(forms.Form):
    """Validate message text and the supported presentation tones."""

    type = forms.ChoiceField(
        choices=[
            (tone, tone.title()) for tone in ("info", "warning", "danger", "success")
        ],
        widget=forms.Select(
            attrs={
                "class" : "input"
            }
        )
    )
    message = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class" : "input"
            }            
        )
    )


def message_config_form(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Return the message editor independently of the selected layout fields."""
    return MessageConfigForm


def show_message(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return one message in the common action-result collection contract."""
    return BehaviorResult(
        messages=(
            BehaviorMessage(
                type=cast(
                    Literal["info", "warning", "danger", "success"], config["type"]
                ),
                message=config["message"],
            ),
        )
    )


SHOW_MESSAGE = BehaviorActionDefinition(
    id="show_message",
    label="Show message",
    description="Show a message to the form user.",
    requires_target_field=False,
    config_form_factory=message_config_form,
    execute=show_message,
)
