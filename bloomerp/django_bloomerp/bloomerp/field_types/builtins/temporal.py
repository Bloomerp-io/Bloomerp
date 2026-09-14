from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.field_types.display_options import LABEL_OPTION
from bloomerp.field_types.lookups import (
    DATE_LOOKUPS,
    NUMERIC_LOOKUPS,
    TIME_LOOKUPS,
    WEEK_LOOKUPS,
)
from bloomerp.field_types.construction import (
    AUTO_NOW_ADD_FIELD_OPTION,
    AUTO_NOW_FIELD_OPTION,
    COMMON_FIELD_OPTIONS,
)
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.form_fields.week_field import WeekFormField
from bloomerp.model_fields.week_field import WeekField
from bloomerp.widgets.week_widget import WeekWidget
from django import forms
from django.db import models
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import BEHAVIORS_DISPLAY_OPTION

DATE_FIELD = FieldTypeDefinition(
    form_factory=form(forms.DateField),
    id="DateField",
    icon="fa-solid fa-calendar-days",
    model_field_cls=models.DateField,
    label="Date Field",
    lookups=tuple(DATE_LOOKUPS),
    construction=FieldConstruction(
        defaults={},
        options=(
            *COMMON_FIELD_OPTIONS,
            AUTO_NOW_FIELD_OPTION,
            AUTO_NOW_ADD_FIELD_OPTION,
        ),
    ),
    widget_factory=widget(forms.widgets.DateInput, attrs={"type": "date"}),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

WEEK_FIELD = FieldTypeDefinition(
    id="WeekField",
    icon="fa-solid fa-calendar-week",
    model_field_cls=WeekField,
    label="Week Field",
    lookups=tuple(WEEK_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 8}, options=tuple(COMMON_FIELD_OPTIONS)
    ),
    widget_factory=widget(WeekWidget, attrs={}),
    form_factory=form(WeekFormField, virtual=False),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

DATE_TIME_FIELD = FieldTypeDefinition(
    form_factory=form(forms.DateTimeField),
    id="DateTimeField",
    icon="fa-solid fa-clock",
    model_field_cls=models.DateTimeField,
    label="DateTime Field",
    lookups=tuple(DATE_LOOKUPS),
    construction=FieldConstruction(
        defaults={},
        options=(
            *COMMON_FIELD_OPTIONS,
            AUTO_NOW_FIELD_OPTION,
            AUTO_NOW_ADD_FIELD_OPTION,
        ),
    ),
    widget_factory=widget(
        forms.widgets.DateTimeInput, attrs={"type": "datetime-local"}
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

TIME_FIELD = FieldTypeDefinition(
    form_factory=form(forms.TimeField),
    id="TimeField",
    icon="fa-solid fa-clock",
    model_field_cls=models.TimeField,
    label="Time Field",
    lookups=tuple(TIME_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    widget_factory=widget(forms.widgets.TimeInput, attrs={}),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

DURATION_FIELD = FieldTypeDefinition(
    form_factory=form(forms.DurationField),
    id="DurationField",
    icon="fa-solid fa-hourglass-half",
    model_field_cls=models.DurationField,
    label="Duration Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("DATE_FIELD", DATE_FIELD)
    registry.register("WEEK_FIELD", WEEK_FIELD)
    registry.register("DATE_TIME_FIELD", DATE_TIME_FIELD)
    registry.register("TIME_FIELD", TIME_FIELD)
    registry.register("DURATION_FIELD", DURATION_FIELD)
