from typing import Any

from django import forms
from django.http import HttpRequest
from pydantic import ValidationError as PydanticValidationError

from bloomerp.form_behaviors.definition import BehaviorConfig
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget


class BehaviorField(forms.JSONField):
    """Stores UI-authored behaviors without executing them."""

    widget = BehaviorBuilderWidget
    request: HttpRequest | None = None

    def clean(self, value: Any) -> dict[str, Any] | None:
        """Validate the new declaration schema and each registered action configuration."""
        cleaned = super().clean(value)
        if cleaned in self.empty_values:
            return None
        if not isinstance(cleaned, dict):
            raise forms.ValidationError("Behaviors must be a structured object.")

        try:
            config = BehaviorConfig.model_validate(cleaned)
        except PydanticValidationError as exc:
            raise forms.ValidationError(
                f"Invalid behavior configuration: {exc}",
            ) from exc

        if not config.behaviors:
            return None

        from bloomerp.filters.compiler import resolve_condition
        from bloomerp.form_behaviors.registry import ACTION_REGISTRY
        from bloomerp.form_behaviors.utils import clean_action_config
        from bloomerp.models.application_field import ApplicationField

        listener = ApplicationField.objects.filter(pk=self.widget.source_field.get("id")).first()
        if listener is None:
            raise forms.ValidationError("Behavior listener is unavailable.")
        available = ApplicationField.objects.filter(
            content_type=listener.content_type,
            pk__in=[item["id"] for item in self.widget.field_catalog],
        )
        for behavior in config.behaviors:
            for group in behavior.conditions:
                for condition in group.conditions:
                    if not available.filter(field=condition.field_path).exists():
                        raise forms.ValidationError("Condition field is not in this layout.")
                    _, _, lookup, _ = resolve_condition(condition, model=listener.get_model())
                    if lookup.get_python_evaluator() is None:
                        raise forms.ValidationError("This condition cannot evaluate draft values.")
            for configured in behavior.actions:
                action = ACTION_REGISTRY.get(configured.action)
                if action is None or not action.get_listener_fields(available).filter(pk=listener.pk).exists():
                    raise forms.ValidationError(f"Unavailable action: {configured.action}.")
                target = None
                if configured.target_field:
                    target = action.get_target_fields(available, listener).filter(field=configured.target_field).first()
                    if target is None:
                        raise forms.ValidationError("Select an eligible target field.")
                target_layout_config = None
                if target is not None:
                    for item in self.widget.field_catalog:
                        if item["name"] == target.field and item.get("fieldType") == "OneToManyField":
                            target_layout_config = {
                                "inline_fields": [column["name"] for column in item.get("columns", [])]
                            }
                            break
                clean_action_config(
                    action,
                    listener,
                    target,
                    configured.config,
                    request=self.request,
                    listener_layout_config=self.widget.listener_layout_config,
                    target_layout_config=target_layout_config,
                )
        return config.to_storage()
