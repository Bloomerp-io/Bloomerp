from dataclasses import dataclass, field as dataclass_field

from bloomerp.field_types.display_options import FieldDisplayOption
from bloomerp.field_types.lookups import BOOLEAN_LOOKUPS, DATE_LOOKUPS, NUMERIC_LOOKUPS, TEXT_LOOKUPS, WEEK_LOOKUPS, Lookup
from bloomerp.field_types.options import AUTO_NOW_ADD_FIELD_OPTION, AUTO_NOW_FIELD_OPTION, BLANK_FIELD_OPTION, COMMON_CHOICE_FIELD_OPTIONS, COMMON_FIELD_OPTIONS, COMMON_RELATION_FIELD_OPTIONS, COMMON_TEXT_FIELD_OPTIONS, DB_INDEX_FIELD_OPTION, DECIMAL_PLACES_FIELD_OPTION, DEFAULT_FIELD_OPTION, HELP_TEXT_FIELD_OPTION, MAX_DIGITS_FIELD_OPTION, NULL_FIELD_OPTION, ON_DELETE_FIELD_OPTION, RELATED_NAME_FIELD_OPTION, TO_FIELD_OPTION, UNIQUE_FIELD_OPTION, UPLOAD_TO_FIELD_OPTION, VERBOSE_NAME_FIELD_OPTION, FieldOption
from bloomerp.form_fields.address_field import AddressFormField
from bloomerp.form_fields.icon_field import IconFormField
from bloomerp.form_fields.ordered_multiple_choice_field import OrderedMultipleChoiceField
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.form_fields.week_field import WeekFormField
from bloomerp.model_fields.address_field import AddressField
from bloomerp.model_fields.icon_field import IconField
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.model_fields.user_field import UserField
from bloomerp.model_fields.week_field import WeekField
from bloomerp.widgets.address_widget import AddressWidget
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.icon_picker_widget import IconPickerWidget
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget
from bloomerp.widgets.ordered_field_select_widget import OrderedFieldSelectWidget
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget
from bloomerp.widgets.select_widget import InputSelectWidget
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget
from bloomerp.widgets.week_widget import WeekWidget
from typing import Optional
from typing import TYPE_CHECKING
from django import forms
from django.db import models
from django.forms import Widget
from enum import Enum
from typing import Any, Callable, Type

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

# ---------------------
# Helper functions
# ---------------------
def get_related_model_field_choices(application_field: "ApplicationField") -> dict[str, Any]:
    from bloomerp.models import ApplicationField
    from django.contrib.contenttypes.models import ContentType

    related_model = application_field.get_related_model()
    if related_model is None:
        return {"choices": []}

    content_type = ContentType.objects.get_for_model(related_model)
    choices = []
    required_values = []
    parent_model = application_field.get_model()
    for related_field in ApplicationField.objects.filter(content_type=content_type).order_by("field"):
        if _is_parent_link_field(related_field, parent_model):
            continue
        try:
            model_field = related_field._get_model_field()
        except Exception:
            continue
        if getattr(model_field, "auto_created", False):
            continue
        if not getattr(model_field, "editable", True):
            continue
        if not getattr(model_field, "concrete", True):
            continue
        choices.append((related_field.field, related_field.title))
        if _is_required_inline_field(related_field):
            required_values.append(related_field.field)
    return {
        "choices": choices,
        "widget": OrderedFieldSelectWidget(
            choices=choices,
            required_values=required_values,
        ),
        "required_values": required_values,
    }


def _is_required_inline_field(application_field: "ApplicationField") -> bool:
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    return (
        not getattr(model_field, "blank", False)
        and not getattr(model_field, "null", False)
        and not getattr(model_field, "auto_created", False)
    )


def _is_parent_link_field(application_field: "ApplicationField", parent_model: type[models.Model] | None) -> bool:
    if parent_model is None:
        return False
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    remote_field = getattr(model_field, "remote_field", None)
    return getattr(remote_field, "model", None) == parent_model




@dataclass(frozen=True)
class FieldTypeDefinition:
    """Definition of a field type with its metadata."""
    id: str  # Internal ID used for lookup (e.g., "ForeignKey")
    display_name: str  # Human-readable name
    description: Optional[str] = None
    icon: str = "fa-solid fa-table-columns"

    # Django model field
    model_field_cls: Optional[type[models.Field]] = None
    default_model_field_args: dict = dataclass_field(default_factory=dict)

    # Additional form field
    form_field_cls : Optional[type[forms.Field]] = None
    default_form_field_args: dict = dataclass_field(default_factory=dict)

    # Widget class or callable that returns a widget class
    widget_cls:Optional[Widget|Callable] = None
    default_widget_args: dict = dataclass_field(default_factory=dict)
    widget_init_kwargs: dict = dataclass_field(default_factory=dict)
    widget_related_model_attr: str | None = "model"
    widget_layout_config_attr: str | None = None
    widget_parent_model_attr: str | None = None
    editable_without_form_field: bool = False

    lookups: list[Lookup] = dataclass_field(default_factory=list)
    allow_in_model: bool = True

    # Field options
    field_options: list[FieldOption] = dataclass_field(default_factory=list)

    # Display options
    field_display_options : list[FieldDisplayOption] = dataclass_field(default_factory=list)

    def get_widget_cls(self) -> Type[Widget]:
        """Returns the widget_cls for the field type."""
        if self.widget_cls:
            return self.widget_cls

        if self.model_field_cls and hasattr(self.model_field_cls, "widget_cls") and self.model_field_cls.widget_cls:
            return self.model_field_cls.widget

        return forms.widgets.TextInput

    def get_form_field_cls(self) -> Type[forms.Field]:
        """Returns the form_field_cls for the field type."""
        if self.form_field_cls:
            return self.form_field_cls

        if self.model_field_cls and hasattr(self.model_field_cls, "form_field_cls") and self.model_field_cls.form_field_cls:
            return self.model_field_cls.form_field_cls

        return forms.CharField

    def build_widget(self, application_field: "ApplicationField", layout_config: dict[str, Any] | None = None) -> forms.Widget:
        """Build the widget for this field type and application field."""
        attrs = {}
        attrs.update(self.default_widget_args)
        if application_field.meta:
            attrs.update(application_field.meta)
        if layout_config and self.widget_layout_config_attr:
            attrs[self.widget_layout_config_attr] = layout_config

        related_model = application_field.get_related_model()
        if related_model and self.widget_related_model_attr:
            attrs[self.widget_related_model_attr] = related_model
        if self.widget_parent_model_attr:
            attrs[self.widget_parent_model_attr] = application_field.get_model()
        
        if self.widget_cls:
            return self.get_widget_cls()(
                attrs=attrs,
                **self.widget_init_kwargs.copy(),
            )

        try:
            model_field = application_field._get_model_field()
        except Exception:
            return self.get_widget_cls()(
                attrs=attrs,
            )

        if not hasattr(model_field, "formfield"):
            return self.get_widget_cls()(
                attrs=attrs,
            )

        form_field = model_field.formfield()
        if form_field is not None and form_field.widget is not None:
            form_field.widget.attrs.update(attrs)
            return form_field.widget

        return self.get_widget_cls()(
            attrs=attrs,
        )


class FieldType(Enum):
    """Enum for field types with display name and Django field class mapping.

    Usage:
        # Get by enum member
        field_type = FieldType.FOREIGN_KEY

        # Get by string ID
        field_type = FieldType.from_id("ForeignKey")

        # Access properties
        field_type.id           # "ForeignKey"
        field_type.display_name # "Foreign Key"
        field_type.model_field_cls  # models.ForeignKey
    """

    # Basic Fields
    PROPERTY = FieldTypeDefinition(
        id="Property",
        display_name="Property",
        icon="fa-solid fa-sliders",
        allow_in_model=False,
    )

    AUTO_FIELD = FieldTypeDefinition(
        id="AutoField",
        display_name="Auto Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.AutoField,
        lookups=NUMERIC_LOOKUPS,
    )

    BIG_AUTO_FIELD = FieldTypeDefinition(
        id="BigAutoField",
        display_name="Big Auto Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.BigAutoField,
        lookups=NUMERIC_LOOKUPS,
    )

    SMALL_AUTO_FIELD = FieldTypeDefinition(
        id="SmallAutoField",
        display_name="Small Auto Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.SmallAutoField,
        lookups=NUMERIC_LOOKUPS,
    )

    # Text Fields
    CHAR_FIELD = FieldTypeDefinition(
        id="CharField",
        display_name="Char Field",
        icon="fa-solid fa-font",
        model_field_cls=models.CharField,
        widget_cls=InputSelectWidget,
        default_model_field_args={
            "max_length": 100,
        },
        lookups=TEXT_LOOKUPS,
        field_options=COMMON_TEXT_FIELD_OPTIONS,
        field_display_options=[
            FieldDisplayOption(
                id="label",
                label="Label",
                form_field_cls=forms.CharField,
                required=False,
            )
        ]
    )

    CHOICE_FIELD = FieldTypeDefinition(
        id="ChoiceField",
        display_name="Choice Field",
        icon="fa-solid fa-list",
        model_field_cls=models.CharField,
        widget_cls=InputSelectWidget,
        lookups=TEXT_LOOKUPS,
        default_model_field_args={
            "max_length": 50,
        },
        field_options=COMMON_CHOICE_FIELD_OPTIONS,
    )

    TEXT_FIELD = FieldTypeDefinition(
        id="TextField",
        display_name="Text Field",
        icon="fa-solid fa-paragraph",
        model_field_cls=models.TextField,
        lookups=TEXT_LOOKUPS,
        widget_cls=BloomerpTextEditorWidget,
        field_options=COMMON_FIELD_OPTIONS,
    )

    EMAIL_FIELD = FieldTypeDefinition(
        id="EmailField",
        display_name="Email Field",
        icon="fa-solid fa-envelope",
        model_field_cls=models.EmailField,
        lookups=TEXT_LOOKUPS,
        default_model_field_args={
            "max_length": 254,
        },
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    URL_FIELD = FieldTypeDefinition(
        id="URLField",
        display_name="URL Field",
        icon="fa-solid fa-link",
        model_field_cls=models.URLField,
        lookups=TEXT_LOOKUPS,
        default_model_field_args={
            "max_length": 200,
        },
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    ADDRESS_FIELD = FieldTypeDefinition(
        id="AddressField",
        display_name="Address Field",
        icon="fa-solid fa-location-dot",
        model_field_cls=AddressField,
        form_field_cls=AddressFormField,
        widget_cls=AddressWidget,
        lookups=TEXT_LOOKUPS,
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    PHONE_NUMBER_FIELD = FieldTypeDefinition(
        id="PhoneNumberField",
        display_name="Phone Number Field",
        icon="fa-solid fa-phone",
        model_field_cls=PhoneNumberField,
        form_field_cls=PhoneNumberFormField,
        widget_cls=PhoneNumberWidget,
        lookups=TEXT_LOOKUPS,
        default_model_field_args={
            "max_length": 30,
        },
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    SLUG_FIELD = FieldTypeDefinition(
        id="SlugField",
        display_name="Slug Field",
        icon="fa-solid fa-tag",
        model_field_cls=models.SlugField,
        lookups=TEXT_LOOKUPS,
        default_model_field_args={
            "max_length": 50,
        },
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    # Numeric Fields
    INTEGER_FIELD = FieldTypeDefinition(
        id="IntegerField",
        display_name="Integer Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.IntegerField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    FLOAT_FIELD = FieldTypeDefinition(
        id="FloatField",
        display_name="Float Field",
        icon="fa-solid fa-calculator",
        model_field_cls=models.FloatField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    DECIMAL_FIELD = FieldTypeDefinition(
        id="DecimalField",
        display_name="Decimal Field",
        icon="fa-solid fa-calculator",
        model_field_cls=models.DecimalField,
        lookups=NUMERIC_LOOKUPS,
        default_model_field_args={
            "max_digits": 10,
            "decimal_places": 2,
        },
        field_options=[
            *COMMON_FIELD_OPTIONS,
            MAX_DIGITS_FIELD_OPTION,
            DECIMAL_PLACES_FIELD_OPTION,
        ],
    )

    POSITIVE_INTEGER_FIELD = FieldTypeDefinition(
        id="PositiveIntegerField",
        display_name="Positive Integer Field",
        icon="fa-solid fa-plus",
        model_field_cls=models.PositiveIntegerField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    POSITIVE_SMALL_INTEGER_FIELD = FieldTypeDefinition(
        id="PositiveSmallIntegerField",
        display_name="Positive Small Integer Field",
        icon="fa-solid fa-plus",
        model_field_cls=models.PositiveSmallIntegerField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    BIG_INTEGER_FIELD = FieldTypeDefinition(
        id="BigIntegerField",
        display_name="Big Integer Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.BigIntegerField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    SMALL_INTEGER_FIELD = FieldTypeDefinition(
        id="SmallIntegerField",
        display_name="Small Integer Field",
        icon="fa-solid fa-hashtag",
        model_field_cls=models.SmallIntegerField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    # Boolean Fields
    BOOLEAN_FIELD = FieldTypeDefinition(
        id="BooleanField",
        display_name="Boolean Field",
        icon="fa-solid fa-toggle-on",
        model_field_cls=models.BooleanField,
        lookups=BOOLEAN_LOOKUPS,
        default_model_field_args={
            "default": False,
        },
        widget_cls=forms.CheckboxInput,
        default_widget_args={
            "style" : "max-width:1.5rem; height:1.5rem", # otherwise this fucker would be w-full
            
        },
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
        field_display_options=[
            
        ]
    )

    NULL_BOOLEAN_FIELD = FieldTypeDefinition(
        id="NullBooleanField",
        display_name="Null Boolean Field",
        icon="fa-solid fa-toggle-on",
        model_field_cls=models.BooleanField,
        lookups=BOOLEAN_LOOKUPS,
        default_model_field_args={
            "null": True,
            "blank": True,
        },
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    # Date/Time Fields  
    DATE_FIELD = FieldTypeDefinition(
        id="DateField",
        display_name="Date Field",
        icon="fa-solid fa-calendar-days",
        model_field_cls=models.DateField,
        lookups=DATE_LOOKUPS,
        widget_cls=forms.widgets.DateInput,
        default_widget_args={
            "type" : "date"
        },
        field_options=[
            *COMMON_FIELD_OPTIONS,
            AUTO_NOW_FIELD_OPTION,
            AUTO_NOW_ADD_FIELD_OPTION,
        ],
    )

    WEEK_FIELD = FieldTypeDefinition(
        id="WeekField",
        display_name="Week Field",
        icon="fa-solid fa-calendar-week",
        model_field_cls=WeekField,
        form_field_cls=WeekFormField,
        widget_cls=WeekWidget,
        default_model_field_args={
            "max_length": 8,
        },
        lookups=WEEK_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    DATE_TIME_FIELD = FieldTypeDefinition(
        id="DateTimeField",
        display_name="DateTime Field",
        icon="fa-solid fa-clock",
        model_field_cls=models.DateTimeField,
        lookups=DATE_LOOKUPS,
        widget_cls=forms.widgets.DateTimeInput,
        default_widget_args={
            "type": "datetime-local"
        },
        field_options=[
            *COMMON_FIELD_OPTIONS,
            AUTO_NOW_FIELD_OPTION,
            AUTO_NOW_ADD_FIELD_OPTION,
        ],
    )

    TIME_FIELD = FieldTypeDefinition(
        id="TimeField",
        display_name="Time Field",
        icon="fa-solid fa-clock",
        model_field_cls=models.TimeField,
        lookups=DATE_LOOKUPS,
        widget_cls=forms.widgets.TimeInput,
        field_options=COMMON_FIELD_OPTIONS,
    )

    DURATION_FIELD = FieldTypeDefinition(
        id="DurationField",
        display_name="Duration Field",
        icon="fa-solid fa-hourglass-half",
        model_field_cls=models.DurationField,
        lookups=NUMERIC_LOOKUPS,
        field_options=COMMON_FIELD_OPTIONS,
    )

    FILE_FIELD = FieldTypeDefinition(
        id="FileField",
        display_name="File Field",
        icon="fa-solid fa-file",
        model_field_cls=models.FileField,
        default_model_field_args={
            "upload_to": "uploads/",
        },
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            UPLOAD_TO_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    IMAGE_FIELD = FieldTypeDefinition(
        id="ImageField",
        display_name="Image Field",
        icon="fa-solid fa-image",
        model_field_cls=models.ImageField,
        default_model_field_args={
            "upload_to": "images/",
        },
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            UPLOAD_TO_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    FOREIGN_KEY = FieldTypeDefinition(
        id="ForeignKey",
        display_name="Foreign Key",
        icon="fa-solid fa-link",
        model_field_cls=models.ForeignKey,
        lookups=[
            Lookup.FOREIGN_EQUALS,
            # TODO: fix this Lookup.FOREIGN_IN,
            Lookup.FOREIGN_ADVANCED,
            Lookup.IS_NULL,
        ],
        form_field_cls=forms.ModelChoiceField,
        widget_cls=ForeignFieldWidget,
        default_widget_args={
            "is_m2m": False
        },
        default_model_field_args={
            "on_delete": models.CASCADE,
        },
        field_options=[
            *COMMON_RELATION_FIELD_OPTIONS,
            ON_DELETE_FIELD_OPTION,
        ],
    )

    ONE_TO_ONE_FIELD = FieldTypeDefinition(
        id="OneToOneField",
        display_name="One To One Field",
        icon="fa-solid fa-link",
        model_field_cls=models.OneToOneField,
        lookups=[
            Lookup.IS_NULL,
            Lookup.EQUALS,
            Lookup.IN,
        ],
        default_model_field_args={
            "on_delete": models.CASCADE,
        },
        field_options=[
            *COMMON_RELATION_FIELD_OPTIONS,
            ON_DELETE_FIELD_OPTION,
            UNIQUE_FIELD_OPTION,
        ],
    )

    MANY_TO_MANY_FIELD = FieldTypeDefinition(
        id="ManyToManyField",
        display_name="Many To Many Field",
        icon="fa-solid fa-share-nodes",
        model_field_cls=models.ManyToManyField,
        lookups=[
            Lookup.EQUALS,
            Lookup.IS_NULL,
            Lookup.IN,
        ],
        widget_cls=ForeignFieldWidget,
        default_widget_args={
            "is_m2m": True
        },
        field_options=[
            TO_FIELD_OPTION,
            VERBOSE_NAME_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    ONE_TO_MANY_FIELD = FieldTypeDefinition(
        id="OneToManyField",
        display_name="One To Many Field",
        icon="fa-solid fa-share-nodes",
        widget_cls=OneToManyFieldWidget,
        widget_related_model_attr="related_model",
        widget_layout_config_attr="layout_config",
        widget_parent_model_attr="parent_model",
        editable_without_form_field=True,
        allow_in_model=False,
        field_display_options=[
            FieldDisplayOption(
                id="label",
                label="Label",
                form_field_cls=forms.CharField,
                required=False,
            ),
            FieldDisplayOption(
                id="inline_fields",
                label="Inline fields",
                form_field_cls=OrderedMultipleChoiceField,
                required=False,
                help_text="Choose which related fields appear as editable columns.",
                get_form_field_kwargs=get_related_model_field_choices,
            ),
        ],
    )

    USER_FIELD = FieldTypeDefinition(
        id="UserField",
        display_name="User Field",
        icon="fa-solid fa-user",
        model_field_cls=UserField,
        widget_cls=ForeignFieldWidget,
        default_widget_args={
            "is_m2m" : False
        },
        lookups=[
            Lookup.IS_NULL,
            Lookup.EQUALS_USER,
            Lookup.FOREIGN_EQUALS
        ],
        field_options=[
            VERBOSE_NAME_FIELD_OPTION,
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DB_INDEX_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
            ON_DELETE_FIELD_OPTION,
        ],
    )

    # Other Fields
    UUID_FIELD = FieldTypeDefinition(
        id="UUIDField",
        display_name="UUID Field",
        icon="fa-solid fa-fingerprint",
        model_field_cls=models.UUIDField,
        lookups=[Lookup.EQUALS, Lookup.IN, Lookup.IS_NULL],
        field_options=COMMON_FIELD_OPTIONS,
    )

    BINARY_FIELD = FieldTypeDefinition(
        id="BinaryField",
        display_name="Binary Field",
        icon="fa-solid fa-code",
        model_field_cls=models.BinaryField,
    )

    IP_ADDRESS_FIELD = FieldTypeDefinition(
        id="IPAddressField",
        display_name="IP Address Field",
        icon="fa-solid fa-network-wired",
        model_field_cls=models.GenericIPAddressField,
        lookups=TEXT_LOOKUPS,
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    GENERIC_IP_ADDRESS_FIELD = FieldTypeDefinition(
        id="GenericIPAddressField",
        display_name="Generic IP Address Field",
        icon="fa-solid fa-network-wired",
        model_field_cls=models.GenericIPAddressField,
        lookups=TEXT_LOOKUPS,
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    JSON_FIELD = FieldTypeDefinition(
        id="JSONField",
        display_name="JSON Field",
        icon="fa-solid fa-code",
        model_field_cls=models.JSONField,
        widget_cls=CodeEditorWidget,
        default_model_field_args={
            "default": dict,
        },
        widget_init_kwargs={
            "language": "json",
        },
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )

    ARRAY_FIELD = FieldTypeDefinition(
        id="ArrayField",
        display_name="Array Field",
        icon="fa-solid fa-list-ol",
        lookups=[
            Lookup.CONTAINS,
            Lookup.IS_NULL
            ],
        allow_in_model=False,
    )

    HSTORE_FIELD = FieldTypeDefinition(
        id="HStoreField",
        display_name="HStore Field",
        icon="fa-solid fa-box-archive",
        allow_in_model=False,

    )

    # Generic Relations
    GENERIC_RELATION = FieldTypeDefinition(
        id="GenericRelation",
        display_name="Generic Relation",
        icon="fa-solid fa-share-nodes",
        allow_in_model=False,

    )

    GENERIC_FOREIGN_KEY = FieldTypeDefinition(
        id="GenericForeignKey",
        display_name="Generic Foreign Key",
        icon="fa-solid fa-link",
        allow_in_model=False,
    )

    # Custom Bloomerp Fields
    STATUS_FIELD = FieldTypeDefinition(
        id="StatusField",
        display_name="Status Field",
        icon="fa-solid fa-signal",
        lookups=TEXT_LOOKUPS,
        allow_in_model=False,
    )

    ICON_FIELD = FieldTypeDefinition(
        id="IconField",
        display_name="Icon Field",
        icon="fa-solid fa-star",
        model_field_cls=IconField,
        form_field_cls=IconFormField,
        widget_cls=IconPickerWidget,
        lookups=TEXT_LOOKUPS,
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )

    BLOOMERP_FILE_FIELD = FieldTypeDefinition(
        id="BloomerpFileField",
        display_name="Bloomerp File Field",
        icon="fa-solid fa-file-lines",
        allow_in_model=False,
    )

    @property
    def id(self) -> str:
        """Returns the internal ID of the field type."""
        return self.value.id

    @property
    def display_name(self) -> str:
        """Returns the human-readable display name."""
        return self.value.display_name

    @property
    def icon(self) -> str:
        """Returns the Font Awesome icon class for the field type."""
        return self.value.icon

    @property
    def model_field_cls(self) -> Optional[type[models.Field]]:
        """Returns the Django field class, if applicable."""
        return self.value.model_field_cls

    @property
    def lookups(self) -> list[Lookup]:
        """Returns the list of supported lookups for this field type."""
        return self.value.lookups

    @property
    def field_options(self) -> list[FieldOption]:
        """Returns the end-user configurable options for this field type."""
        return self.value.field_options

    @property
    def filter_config(self) -> dict:
        """Returns additional filter configuration for this field type."""
        return self.value.filter_config

    @classmethod
    def from_id(cls, field_id: str) -> "FieldType":
        """Get a FieldType by its string ID.

        Args:
            field_id: The internal ID string (e.g., "ForeignKey", "CharField")

        Returns:
            The matching FieldType enum member

        Raises:
            ValueError: If no matching field type is found
        """
        for member in cls:
            if member.value.id == field_id:
                return member
        raise ValueError(f"Unknown field type: {field_id}")

    @classmethod
    def from_model_field_cls(cls, model_field_cls: type[models.Field]) -> Optional["FieldType"]:
        """Get a FieldType by its Django field class.

        Args:
            model_field_cls: The Django field class (e.g., models.ForeignKey)

        Returns:
            The matching FieldType enum member, or None if not found
        """
        for candidate_cls in model_field_cls.__mro__:
            for member in cls:
                if member.value.model_field_cls == candidate_cls:
                    return member
        return None

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Returns choices suitable for Django model field choices."""
        return [(member.id, member.display_name) for member in cls]

    @classmethod
    def template_context(cls, field_type: "FieldType | str | None") -> dict[str, bool]:
        """Generate a dict of boolean flags for template comparisons.

        Django templates cannot compare enum members directly, so this method
        generates a dict where each key is a snake_case version of the enum
        member name, and the value is True if it matches the given field_type.

        Args:
            field_type: A FieldType enum member, a field type ID string, or None

        Returns:
            Dict with boolean flags, e.g., {'foreign_key': True, 'char_field': False, ...}

        Usage in view:
            context['is_field_type'] = FieldType.template_context(application_field.field_type)

        Usage in template:
            {% if is_field_type.foreign_key %}...{% endif %}
        """
        # Convert string to enum if needed
        if isinstance(field_type, str):
            try:
                field_type = cls.from_id(field_type)
            except ValueError:
                field_type = None

        # Generate boolean dict for all enum members
        return {
            member.name.lower(): member == field_type
            for member in cls
        }

    def get_lookup_by_id(self, lookup_id: str) -> Optional[Lookup]:
        """Get a Lookup enum member by its ID for this field type.

        Args:
            lookup_id: The ID of the lookup (e.g., "equals", "icontains")

        Returns:
            The matching Lookup enum member, or None if not found
        """
        for lookup in self.lookups:
            if lookup.value.id == lookup_id:
                return lookup
        return None

    def get_widget_cls(self) -> Optional[Type[Widget]]:
        """Returns the widget_cls for the field class

        Returns:
            Widget: the Django widget_cls object
        """
        if self.value.widget_cls:
            return self.value.widget_cls

        if (
            self.value.model_field_cls
            and hasattr(self.value.model_field_cls, "widget_cls")
            and self.value.model_field_cls.widget_cls):
            return self.value.model_field_cls.widget_cls

        return forms.widgets.TextInput


