from datetime import date
from typing import Any, Mapping
from django.db.models import QuerySet

from django import forms

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.form_fields.week_field import normalize_week_value
from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField
from .set_o2m_value import collection_rows


def populate_week_dates_config_form_factory(
    target: ApplicationField,
    listener: ApplicationField | None,
) -> type[forms.Form]:
    """Build source-week and related-date choices for the selected collection."""
    Model = target.get_model()

    fields = {}

    fields["write_policy"] = forms.ChoiceField(
        choices=(("if_empty", "Only when empty"), ("replace", "Replace all rows")),
        initial="if_empty",
    )

    fields["source"] = forms.ModelChoiceField(
        queryset=ApplicationField.get_for_model(Model).filter(
            field_type=FIELD_TYPE_REGISTRY.WEEK_FIELD.id
        )
    )

    fields["column"] = forms.ModelChoiceField(
        queryset=ApplicationField.get_for_model(
            target.get_related_model()  # Assuming that it is a O2M which has been validated before
        ).filter(field_type=FIELD_TYPE_REGISTRY.DATE_FIELD.id)
    )

    fields["days"] = forms.TypedChoiceField(
        choices=((5, "Monday–Friday"), (7, "Monday–Sunday")),
        coerce=int,
        initial=5,
    )

    return type("PopulateWeekDaysForm", (forms.Form,), fields)


def populate_week_dates(
    context: BehaviorContext, config: Mapping[str, Any]
) -> BehaviorResult:
    """Generate dated collection values from the configured source week."""
    if config["source"].field not in context.values:
        raise forms.ValidationError("The source week is missing from the draft.")
    week = normalize_week_value(context.values[config["source"].field])
    date_column = config["column"].field
    if not week:
        return BehaviorResult()
    if date_column in {"id", "DELETE"}:
        raise forms.ValidationError(
            "Choose a date column, not row identity or deletion."
        )
    current = collection_rows(context.target_value)
    if current and config["write_policy"] == "if_empty":
        return BehaviorResult()
    
    rows = [
        {date_column: date.fromisocalendar(week.year, week.week, day).isoformat()}
        for day in range(1, config["days"] + 1)
    ]
    
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.target_field, value=rows),)
    )


def get_week_date_targets(
    fields: QuerySet[ApplicationField],
    listener: ApplicationField | None,
) -> QuerySet[ApplicationField]:
    """Limit week population targets to one-to-many field values."""
    return fields.filter(field_type=FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id)


POPULATE_WEEK_DATES = BehaviorActionDefinition(
    id="populate_week_dates",
    label="Populate dates from week",
    description="Generate five or seven dated rows from the source ISO week.",
    requires_target_field=True,
    execute=populate_week_dates,
    config_form_factory=populate_week_dates_config_form_factory,
    get_target_fields=get_week_date_targets,
)
