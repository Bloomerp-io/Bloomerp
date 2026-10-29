"""Restrict a relationship picker using filters resolved from the current draft."""

from typing import Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from bloomerp.filters.definition import Filter
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.form_behaviors.builtins.fetch import (
    filter_value_references,
    parse_filters,
    resolve_behavior_field_references,
    resolve_filter_values,
)
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition, BehaviorContext, BehaviorResult, BehaviorUser,
    CleanedConfigData, FieldStateUpdate,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


def supports_choice_filter(field: ApplicationField) -> bool:
    """Accept only relationships rendered with the foreign-field picker."""
    return field.get_related_model() is not None and isinstance(
        field.get_widget(layout_config=getattr(field, "_behavior_layout_config", {})),
        ForeignFieldWidget,
    )


def add_filter_targets(
    fields: QuerySet[ApplicationField], listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Offer only fields whose actual widget supports filtered choices."""
    return fields.filter(pk__in=[field.pk for field in fields if supports_choice_filter(field)])


def add_filter_config_form_factory(
    target: ApplicationField | None,
    listener: ApplicationField | None,
    request: HttpRequest | None = None,
) -> type[forms.Form]:
    """Build a JSON editor that preserves typed draft references in filter values."""
    if target is None or not supports_choice_filter(target):
        raise forms.ValidationError(_("Select a relationship using the foreign-field widget."))

    class AddFilterForm(forms.Form):
        """Configure additional choice restrictions without changing selected values."""

        filters = forms.JSONField(
            label=_("Filters"), required=False,
            widget=CodeEditorWidget(language="json"),
            help_text=_("Use {{ object.field }} for a current form value. Empty filters remove the behavior restriction."),
        )

        def clean(self) -> dict[str, Any]:
            """Reject unknown draft references and register them for permission checks."""
            cleaned = super().clean()
            filters = parse_filters(cleaned.get("filters"))
            cleaned["filters"] = filters
            cleaned["value_references"] = resolve_behavior_field_references(
                filters, object_model=target.get_model(),
            )
            cleaned["related_model"] = target.get_related_model()
            return cleaned

    return AddFilterForm


def add_filter(
    context: BehaviorContext, config: CleanedConfigData, user: BehaviorUser,
) -> BehaviorResult:
    """Resolve and authorize the filter; blank dependencies deliberately offer no choices."""
    model = config["related_model"]
    filters = resolve_filter_values(config["filters"], object_values=context.values)
    UserPolicyManager(user).validate_filters(model, filters)
    if any(
        context.values[name] in (None, "", [])
        for _, name in filter_value_references(config["filters"])
    ):
        filters = [Filter(connector="OR", conditions=[])]
    # Compile without evaluating the queryset to validate lookup names and values.
    ModelFilterManager(model).apply(filters, queryset=model._default_manager.all())
    return BehaviorResult(states=(FieldStateUpdate(
        field=context.target_field,
        choices_filter=[group.model_dump(mode="json") for group in filters],
    ),))


ADD_FILTER = BehaviorActionDefinition(
    id="add_filter",
    label=_("Add filter"),
    description=_("Restrict relationship choices using current form values."),
    requires_target_field=True,
    execute=add_filter,
    config_form_factory=add_filter_config_form_factory,
    get_target_fields=add_filter_targets,
    group=_("Field state"),
)
