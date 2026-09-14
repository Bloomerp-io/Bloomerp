from bloomerp.field_types.utils.form_field_factories import form
from django import forms
from bloomerp.field_types.display_options import LABEL_OPTION
from bloomerp.field_types.lookups import NUMERIC_LOOKUPS
from bloomerp.field_types.construction import (
    COMMON_FIELD_OPTIONS,
    DECIMAL_PLACES_FIELD_OPTION,
    MAX_DIGITS_FIELD_OPTION,
)
from django.db import models
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import BEHAVIORS_DISPLAY_OPTION

AUTO_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="AutoField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.AutoField,
    label="Auto Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
BIG_AUTO_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="BigAutoField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.BigAutoField,
    label="Big Auto Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
SMALL_AUTO_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="SmallAutoField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.SmallAutoField,
    label="Small Auto Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
INTEGER_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="IntegerField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.IntegerField,
    label="Integer Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
FLOAT_FIELD = FieldTypeDefinition(
    form_factory=form(forms.FloatField),
    id="FloatField",
    icon="fa-solid fa-calculator",
    model_field_cls=models.FloatField,
    label="Float Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
DECIMAL_FIELD = FieldTypeDefinition(
    form_factory=form(forms.DecimalField),
    id="DecimalField",
    icon="fa-solid fa-calculator",
    model_field_cls=models.DecimalField,
    label="Decimal Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_digits": 10, "decimal_places": 2},
        options=(
            *COMMON_FIELD_OPTIONS,
            MAX_DIGITS_FIELD_OPTION,
            DECIMAL_PLACES_FIELD_OPTION,
        ),
    ),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
POSITIVE_INTEGER_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="PositiveIntegerField",
    icon="fa-solid fa-plus",
    model_field_cls=models.PositiveIntegerField,
    label="Positive Integer Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
POSITIVE_SMALL_INTEGER_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="PositiveSmallIntegerField",
    icon="fa-solid fa-plus",
    model_field_cls=models.PositiveSmallIntegerField,
    label="Positive Small Integer Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
BIG_INTEGER_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="BigIntegerField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.BigIntegerField,
    label="Big Integer Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)
SMALL_INTEGER_FIELD = FieldTypeDefinition(
    form_factory=form(forms.IntegerField),
    id="SmallIntegerField",
    icon="fa-solid fa-hashtag",
    model_field_cls=models.SmallIntegerField,
    label="Small Integer Field",
    lookups=tuple(NUMERIC_LOOKUPS),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("AUTO_FIELD", AUTO_FIELD)
    registry.register("BIG_AUTO_FIELD", BIG_AUTO_FIELD)
    registry.register("SMALL_AUTO_FIELD", SMALL_AUTO_FIELD)
    registry.register("INTEGER_FIELD", INTEGER_FIELD)
    registry.register("FLOAT_FIELD", FLOAT_FIELD)
    registry.register("DECIMAL_FIELD", DECIMAL_FIELD)
    registry.register("POSITIVE_INTEGER_FIELD", POSITIVE_INTEGER_FIELD)
    registry.register("POSITIVE_SMALL_INTEGER_FIELD", POSITIVE_SMALL_INTEGER_FIELD)
    registry.register("BIG_INTEGER_FIELD", BIG_INTEGER_FIELD)
    registry.register("SMALL_INTEGER_FIELD", SMALL_INTEGER_FIELD)
