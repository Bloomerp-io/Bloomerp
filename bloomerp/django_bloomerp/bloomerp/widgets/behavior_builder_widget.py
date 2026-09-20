"""Django adapter for the backend-defined behavior editor."""
import json
from typing import Any, Mapping

from django import forms
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.urls import reverse
from bloomerp.form_behaviors.definition import BehaviorConfig


class BehaviorBuilderWidget(forms.Widget):
    """Edit versioned behavior declarations using registered actions and filters."""

    template_name = "widgets/behavior_builder_widget.html"

    def __init__(
        self, attrs: dict[str, Any] | None = None, *,
        source_field: dict[str, str] | None = None,
        field_catalog: list[dict[str, Any]] | None = None,
    ) -> None:
        """Retain field metadata and allow the owning form to supply layout scope."""
        super().__init__(attrs)
        self.source_field = source_field or {}
        self.field_catalog = field_catalog or []
        self.layout_context: dict[str, Any] = {}

    def format_value(self, value: Any) -> str:
        """Serialize declarations, normalizing Django JSONField's empty JSON value."""
        if isinstance(value, BehaviorConfig):
            value = value.to_storage()
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return value
        if value in (None, "", [], {}):
            value = {"version": 1, "behaviors": []}
        return json.dumps(value, ensure_ascii=False)

    def value_from_datadict(self, data: Mapping[str, Any], files: Any, name: str) -> Any:
        """Read the single JSON field owned by this composite widget."""
        return data.get(name)

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:
        """Publish applicable action metadata and supported condition fields."""
        from bloomerp.form_behaviors.registry import ACTION_REGISTRY
        from bloomerp.models.application_field import ApplicationField
        from bloomerp.filters.resolver import FilterFieldResolver, resolve_lookup

        context = super().get_context(name, value, attrs)
        listener = ApplicationField.objects.filter(pk=self.source_field.get("id")).first()
        actions, condition_fields = [], []
        if listener is not None:
            available = ApplicationField.objects.filter(
                content_type=listener.content_type,
                pk__in=[item["id"] for item in self.field_catalog],
            )
            for action in ACTION_REGISTRY.values():
                if action.get_listener_fields(available).filter(pk=listener.pk).exists():
                    actions.append({
                        "id": action.id, "label": action.label,
                        "requires_target_field": action.requires_target_field,
                        "targets": [{"name": f.field, "label": f.title} for f in action.get_target_fields(available, listener)],
                    })
            resolver = FilterFieldResolver.for_model(listener.get_model())
            for field in available:
                try:
                    resolved, target = resolver.resolve(field.field)
                    lookups = []
                    for definition in field.get_field_type().lookups:
                        lookup = resolve_lookup(resolved, target, definition.id)
                        if not lookup.nested and lookup.get_python_evaluator() is not None:
                            lookups.append({"id": lookup.id, "label": lookup.label, "nested": False})
                    if lookups:
                        condition_fields.append({"field": field.field, "label": field.title, "lookups": lookups})
                except (FieldDoesNotExist, ValidationError, LookupError, ValueError):
                    continue
        context["widget"].update({
            "value": self.format_value(value), "listener_id": str(self.source_field.get("id", "")),
            "content_type_id": listener.content_type_id if listener else "",
            "actions_json": json.dumps(actions), "conditions_json": json.dumps(condition_fields),
            "layout_context_json": json.dumps(self.layout_context),
            "action_url": reverse("components_render_action_form"),
            "value_editor_url": reverse("components_filters_value_editor"),
        })
        return context
