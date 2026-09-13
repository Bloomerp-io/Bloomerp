from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.field_types.display_options import LABEL_OPTION
from bloomerp.field_types.lookups import BOOLEAN_LOOKUPS
from bloomerp.field_types.construction import (
    BLANK_FIELD_OPTION,
    DEFAULT_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
    NULL_FIELD_OPTION,
)
from django import forms
from django.db import models
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import BEHAVIORS_DISPLAY_OPTION
from bloomerp.field_types.utils.widget_factories import widget

BOOLEAN_FIELD = FieldTypeDefinition(
    form_factory=form(forms.BooleanField),
    id="BooleanField",
    icon="fa-solid fa-toggle-on",
    model_field_cls=models.BooleanField,
    label="Boolean Field",
    lookups=tuple(BOOLEAN_LOOKUPS),
    construction=FieldConstruction(
        defaults={"default": False},
        options=(
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    widget_factory=widget(
        forms.CheckboxInput, attrs={"style": "max-width:1.5rem; height:1.5rem"}
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
NULL_BOOLEAN_FIELD = FieldTypeDefinition(
    form_factory=form(forms.NullBooleanField),
    id="NullBooleanField",
    icon="fa-solid fa-toggle-on",
    model_field_cls=models.BooleanField,
    label="Null Boolean Field",
    lookups=tuple(BOOLEAN_LOOKUPS),
    construction=FieldConstruction(
        defaults={"null": True, "blank": True},
        options=(
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("BOOLEAN_FIELD", BOOLEAN_FIELD)
    registry.register("NULL_BOOLEAN_FIELD", NULL_BOOLEAN_FIELD)
