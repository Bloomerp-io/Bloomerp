from __future__ import annotations

from typing import Any, TYPE_CHECKING
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import FieldDoesNotExist
from bloomerp.field_types.display_options import FieldDisplayOption
from bloomerp.form_fields.choice_colors_field import ChoiceColorsField
from bloomerp.widgets.colored_choices_widget import ColoredChoicesWidget
from bloomerp.widgets.choice_color_mapping_widget import ChoiceColorMappingWidget

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

from django import forms
from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.lookups import builtins as lookups
from bloomerp.field_types.construction import (
    BLANK_FIELD_OPTION,
    COMMON_CHOICE_FIELD_OPTIONS,
    COMMON_FIELD_OPTIONS,
    COMMON_TEXT_FIELD_OPTIONS,
    HELP_TEXT_FIELD_OPTION,
    NULL_FIELD_OPTION,
)
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.form_fields.address_field import AddressFormField
from bloomerp.form_fields.icon_field import IconFormField
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.model_fields.address_field import AddressField
from bloomerp.model_fields.code_field import CodeField
from bloomerp.model_fields.icon_field import IconField
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.widgets.address_widget import AddressWidget
from bloomerp.widgets.icon_picker_widget import IconPickerWidget
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget
from bloomerp.widgets.select_widget import InputSelectWidget
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget
from django.db import models
from django_countries.fields import CountryField
from bloomerp.field_types.registry import (
    FieldContext,
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import standard_display_options
from bloomerp.field_types.lookups import TEXT_LOOKUPS


def choice_colors_option(application_field: ApplicationField) -> forms.Field:
    """Build editable mappings restricted to the field's current choice values."""
    choices = (application_field.meta or {}).get("choices", [])
    left_field = forms.ChoiceField(choices=[("", _("Choose value")), *choices])
    right_field = forms.RegexField(
        regex=r"^#[0-9a-fA-F]{6}$",
        widget=forms.TextInput(attrs={"type": "color"}),
    )
    return ChoiceColorsField(
        left=choices,
        left_field=left_field,
        right_field=right_field,
        allow_adding_groups=True,
        widget=ChoiceColorMappingWidget(
            left=choices,
            left_widget=left_field.widget,
            right_widget=right_field.widget,
            allow_adding_groups=True,
        ),
    )


def choice_display_options(
    application_field: ApplicationField,
) -> tuple[FieldDisplayOption, ...]:
    """Offer color settings only while a text field has configured choices."""
    options = standard_display_options(application_field)
    if not (application_field.meta or {}).get("choices"):
        return options
    return (
        *options,
        FieldDisplayOption(
            id="choice_colors",
            label=_("Choice colors"),
            form_factory=choice_colors_option,
            help_text=_(
                "Choose a color for each value. Colors for removed choices are ignored."
            ),
        ),
    )


def choice_widget(context: FieldContext) -> forms.Widget:
    """Use a colored select for choices and a text input when choices disappear."""
    attrs: dict[str, Any] = dict(context.attrs)
    choices = attrs.pop("choices", []) or []
    if not choices:
        return InputSelectWidget(attrs=attrs)
    attrs.pop("colored_choices", None)
    attrs.pop("colors", None)
    allows_blank = False
    if context.application_field is not None:
        try:
            allows_blank = context.application_field._get_model_field().blank
        except FieldDoesNotExist:
            pass
    if allows_blank and not any(str(key) == "" for key, _label in choices):
        choices = [("", "---------"), *choices]
    return ColoredChoicesWidget(
        attrs=attrs,
        choices=choices,
        colors=context.layout_config.get("choice_colors", {}),
    )


def render_choice_value(application_field: ApplicationField, instance: models.Model) -> Any:
    """Display declared choice labels in the active locale, preserving ordinary text."""
    value = getattr(instance, application_field.field, None)
    try:
        field = instance._meta.get_field(application_field.field)
    except FieldDoesNotExist:
        return value
    for key, label in field.flatchoices:
        if key == value:
            return force_str(label)
    return value


CHAR_FIELD = FieldTypeDefinition(
    render_value=render_choice_value,
    form_factory=form(forms.CharField),
    widget_factory=choice_widget,
    id="CharField",
    icon="fa-solid fa-font",
    model_field_cls=models.CharField,
    label="Char Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 255}, options=COMMON_TEXT_FIELD_OPTIONS
    ),
    display_options=choice_display_options,
)
CODE_FIELD = FieldTypeDefinition(
    id="CodeField",
    icon="fa-solid fa-code",
    model_field_cls=CodeField,
    label="Code Field",
    lookups=(),
    display_options=standard_display_options,
)
CHOICE_FIELD = FieldTypeDefinition(
    render_value=render_choice_value,
    id="ChoiceField",
    icon="fa-solid fa-list",
    model_field_cls=models.CharField,
    label="Choice Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 255}, options=tuple(COMMON_CHOICE_FIELD_OPTIONS)
    ),
    widget_factory=choice_widget,
    display_options=choice_display_options,
)
TEXT_FIELD = FieldTypeDefinition(
    form_factory=form(forms.CharField),
    id="TextField",
    icon="fa-solid fa-align-left",
    model_field_cls=models.TextField,
    label="Text Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(options=COMMON_FIELD_OPTIONS),
    widget_factory=widget(BloomerpTextEditorWidget, attrs={}),
    display_options=standard_display_options,
)
EMAIL_FIELD = FieldTypeDefinition(
    id="EmailField",
    icon="fa-solid fa-envelope",
    model_field_cls=models.EmailField,
    label="Email Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 254}, options=COMMON_TEXT_FIELD_OPTIONS
    ),
    display_options=standard_display_options,
    render_value=lambda application_field, instance: (
        f"<a href='mailto:{getattr(instance, application_field.field)}'>{getattr(instance, application_field.field)}</a>"
    ),
)
URL_FIELD = FieldTypeDefinition(
    id="URLField",
    icon="fa-solid fa-link",
    model_field_cls=models.URLField,
    label="URL Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 200}, options=COMMON_TEXT_FIELD_OPTIONS
    ),
    display_options=standard_display_options,
    render_value=lambda application_field, instance: (
        f"<a href='{getattr(instance, application_field.field)}'>{getattr(instance, application_field.field)}</a>"
    ),
)
ADDRESS_FIELD = FieldTypeDefinition(
    id="AddressField",
    icon="fa-solid fa-location-dot",
    model_field_cls=AddressField,
    label="Address Field",
    lookups=(lookups.ADDRESS_CONTAINS,),
    construction=FieldConstruction(
        options=(NULL_FIELD_OPTION, BLANK_FIELD_OPTION, HELP_TEXT_FIELD_OPTION)
    ),
    widget_factory=widget(AddressWidget, attrs={}),
    form_factory=form(AddressFormField, virtual=False),
    display_options=standard_display_options,
)
PHONE_NUMBER_FIELD = FieldTypeDefinition(
    id="PhoneNumberField",
    icon="fa-solid fa-phone",
    model_field_cls=PhoneNumberField,
    label="Phone Number Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 30}, options=tuple(COMMON_TEXT_FIELD_OPTIONS)
    ),
    widget_factory=widget(PhoneNumberWidget, attrs={}),
    form_factory=form(PhoneNumberFormField, virtual=False),
    display_options=standard_display_options,
)
SLUG_FIELD = FieldTypeDefinition(
    id="SlugField",
    icon="fa-solid fa-tag",
    model_field_cls=models.SlugField,
    label="Slug Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={"max_length": 50}, options=tuple(COMMON_TEXT_FIELD_OPTIONS)
    ),
    display_options=standard_display_options,
)
IP_ADDRESS_FIELD = FieldTypeDefinition(
    id="IPAddressField",
    icon="fa-solid fa-network-wired",
    model_field_cls=models.GenericIPAddressField,
    label="IP Address Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={}, options=tuple(COMMON_TEXT_FIELD_OPTIONS)
    ),
    display_options=standard_display_options,
)
GENERIC_IP_ADDRESS_FIELD = FieldTypeDefinition(
    id="GenericIPAddressField",
    icon="fa-solid fa-network-wired",
    model_field_cls=models.GenericIPAddressField,
    label="Generic IP Address Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={}, options=tuple(COMMON_TEXT_FIELD_OPTIONS)
    ),
    display_options=standard_display_options,
)
ICON_FIELD = FieldTypeDefinition(
    id="IconField",
    icon="fa-solid fa-star",
    model_field_cls=IconField,
    label="Icon Field",
    lookups=tuple(TEXT_LOOKUPS),
    construction=FieldConstruction(
        defaults={}, options=tuple(COMMON_TEXT_FIELD_OPTIONS)
    ),
    widget_factory=widget(IconPickerWidget, attrs={}),
    form_factory=form(IconFormField, virtual=False),
    display_options=standard_display_options,
)
COUNTRY_FIELD = FieldTypeDefinition(
    id="CountryField",
    icon="fa-solid fa-globe",
    model_field_cls=CountryField,
    label="Country Field",
    lookups=(lookups.EQUALS, lookups.NOT_EQUALS, lookups.VALUES_IN, lookups.IS_NULL),
    construction=FieldConstruction(defaults={}, options=tuple(COMMON_FIELD_OPTIONS)),
    display_options=standard_display_options,
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("CHAR_FIELD", CHAR_FIELD)
    registry.register("CODE_FIELD", CODE_FIELD)
    registry.register("CHOICE_FIELD", CHOICE_FIELD)
    registry.register("TEXT_FIELD", TEXT_FIELD)
    registry.register("EMAIL_FIELD", EMAIL_FIELD)
    registry.register("URL_FIELD", URL_FIELD)
    registry.register("ADDRESS_FIELD", ADDRESS_FIELD)
    registry.register("PHONE_NUMBER_FIELD", PHONE_NUMBER_FIELD)
    registry.register("SLUG_FIELD", SLUG_FIELD)
    registry.register("IP_ADDRESS_FIELD", IP_ADDRESS_FIELD)
    registry.register("GENERIC_IP_ADDRESS_FIELD", GENERIC_IP_ADDRESS_FIELD)
    registry.register("ICON_FIELD", ICON_FIELD)
    registry.register("COUNTRY_FIELD", COUNTRY_FIELD)
