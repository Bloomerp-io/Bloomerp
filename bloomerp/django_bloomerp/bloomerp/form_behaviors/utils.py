"""Bind portable action configuration to Django forms for editing and saving."""

from __future__ import annotations

import json
from typing import Any, Mapping
from django import forms
from django.core.exceptions import ValidationError
from bloomerp.form_behaviors.definition import BehaviorActionDefinition
from bloomerp.models.application_field import ApplicationField


def build_action_config_form(
    action: BehaviorActionDefinition,
    listener_field: ApplicationField | None = None,
    target_field: ApplicationField | None = None,
) -> type[forms.Form]:
    """Return the action's form class after the separate target selection step."""
    if action.requires_target_field and target_field is None:
        raise ValidationError("Select a target field first.")
    return action.config_form_factory(target_field, listener_field)


def action_config_form(
    action: BehaviorActionDefinition,
    listener: ApplicationField | None,
    target: ApplicationField | None,
    config: Mapping[str, Any],
    *,
    prefix: str = "",
    bound: bool = False,
) -> forms.Form:
    """Create a prefixed editor or validator, resolving portable field-name choices."""
    form_class = build_action_config_form(action, listener, target)
    values = dict(config)
    form = form_class(prefix=prefix, initial=values.copy())
    known_fields = set(form.fields) if bound else set(form.fields) | set(form_class.base_fields)
    if set(values) - known_fields:
        raise ValidationError("Unknown action configuration fields.")
    for name, field in form.fields.items():
        if (
            isinstance(field, forms.ModelChoiceField)
            and field.queryset.model is ApplicationField
        ):
            field.to_field_name = "field"
        if bound and name in values and isinstance(field, forms.JSONField):
            values[name] = json.dumps(values[name])
    if bound:
        form.data = {form.add_prefix(name): value for name, value in values.items()}
        form.is_bound = True
    return form


def clean_action_config(
    action: BehaviorActionDefinition,
    listener: ApplicationField | None,
    target: ApplicationField | None,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate portable JSON configuration using the same form used by the editor."""
    form = action_config_form(action, listener, target, config, bound=True)
    if not form.is_valid():
        raise ValidationError(form.errors.as_json())
    return form.cleaned_data
