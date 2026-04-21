from dataclasses import dataclass, field as dataclass_field
from typing import Literal, Optional, Callable, Any, Type
from unittest.util import _MAX_LENGTH
from django.db import models
from enum import Enum
from django.forms import Widget
import django_filters
from bloomerp.model_fields.user_field import UserField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django import forms
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.model_fields.icon_field import IconField
from bloomerp.form_fields.icon_field import IconFormField
from bloomerp.widgets.icon_picker_widget import IconPickerWidget
from bloomerp.widgets.select_widget import InputSelectWidget
from typing import TYPE_CHECKING
from django.contrib.contenttypes.models import ContentType

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

def render_foreign_key_field(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    field_name = name_override or application_field.field
    widget_attrs = {}
    widget_attrs.update(application_field.meta or {})
    return ForeignFieldWidget(attrs=widget_attrs).render(
        name=field_name,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
    
def render_foreign_key_in(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    field_name = name_override or application_field.field
    widget_attrs = {}
    widget_attrs.update(application_field.meta or {})
    return ForeignFieldWidget(attrs=widget_attrs).render(
        name=field_name,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
    
def render_equals_current_user(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    field_name = name_override or application_field.field
    return forms.CharField.widget_cls().render(
        name=field_name,
        value="$user",
        attrs={
            "class" : "input w-full",
            "disabled" : True
        }
    )

def render_advanced_lookup(application_field:"ApplicationField", name_override: Optional[str] = None) -> str:
    from bloomerp.models import ApplicationField
    
    related_model = application_field.related_model
    
    objects = ApplicationField.objects.filter(
        content_type=ContentType.objects.get_for_model(related_model)
    )
    
    html = "<select class='select'>"
    for obj in objects:
        html += f"<option value='{obj.id}'>{obj.title}</option>"
    
    html += "</select>"
    
    return html

@dataclass
class LookupDefinition:
    id: str
    display_name: str
    django_representation: str  # The Django ORM lookup (e.g., "icontains", "gte")
    description: Optional[str] = None
    
    # Filter configuration for django-filters
    filter_class: Optional[type] = None  # e.g., django_filters.CharFilter
    aliases: list[str] = dataclass_field(default_factory=list)  # Alternative field name patterns: ["", "__exact", "__equals"]
    
    # For special filter configurations (e.g., ModelMultipleChoiceFilter needs queryset)
    get_filter_kwargs: Optional[Callable[[Any], dict]] = None  # Function that returns extra kwargs  
    render_func : Optional[Callable] = None
    
    def render(self, application_field, name_override: Optional[str] = None) -> str:
        if not self.render_func:
            field_name = name_override or application_field.field
            return f"""<input type=\"text\" class=\"input w-full\" name=\"{field_name}\">"""

        return self.render_func(application_field, name_override=name_override)
        

class Lookup(Enum):
    EQUALS = LookupDefinition(
        id="equals",
        display_name="Equals",
        django_representation="exact",
        aliases=["", "__exact", "__equals"],  # Can use field_name, field_name__exact, or field_name__equals
        filter_class=django_filters.CharFilter
    )
    
    IEXACT = LookupDefinition(
        id="iexact",
        display_name="Equals (case-insensitive)",
        django_representation="iexact",
        aliases=["__iexact"],
        description="Case-insensitive exact match."
    )
    
    CONTAINS = LookupDefinition(
        id="contains",
        display_name="Contains",
        django_representation="icontains",
        aliases=["__icontains", "__contains"],
        description="Containment test (generated as icontains by default)."
    )
    
    STARTS_WITH = LookupDefinition(
        id="starts_with",
        display_name="Starts With",
        django_representation="startswith",
        aliases=["__startswith", "__istartswith"],
        description="Starts with test."
    )
    
    ENDS_WITH = LookupDefinition(
        id="ends_with",
        display_name="Ends With",
        django_representation="endswith",
        aliases=["__endswith", "__iendswith"],
        description="Ends with test."
    )
    
    GREATER_THAN = LookupDefinition(
        id="greater_than",
        display_name="Greater Than",
        django_representation="gt",
        aliases=["__gt"]
    )
    
    GREATER_THAN_OR_EQUAL = LookupDefinition(
        id="greater_than_or_equal",
        display_name="Greater Than or Equal",
        django_representation="gte",
        aliases=["__gte"]
    )
    
    LESS_THAN = LookupDefinition(
        id="less_than",
        display_name="Less Than",
        django_representation="lt",
        aliases=["__lt"]
    )
    
    LESS_THAN_OR_EQUAL = LookupDefinition(
        id="less_than_or_equal",
        display_name="Less Than or Equal",
        django_representation="lte",
        aliases=["__lte"]
    )
    
    IN = LookupDefinition(
        id="in",
        display_name="In",
        django_representation="in",
        aliases=["__in"],
        description="Checks if value is in a list of values."
    )
    
    IS_NULL = LookupDefinition(
        id="is_null",
        display_name="Is Null",
        django_representation="isnull",
        aliases=["__isnull"],
        description="Checks if value is null (True) or not null (False)."
    )
    
    NOT_EQUALS = LookupDefinition(
        id="not_equals",
        display_name="Not Equals",
        django_representation="ne",
        description="Not equal comparison."
    )
    
    EQUALS_USER = LookupDefinition(
        id="equals_user",
        display_name="Equals Current User",
        django_representation="",
        render_func=render_equals_current_user
    )
    
    FOREIGN_EQUALS = LookupDefinition(
        id="foreign_equals",
        display_name="Equals",
        django_representation="exact",
        render_func=render_foreign_key_field
    )
    
    FOREIGN_IN = LookupDefinition(
        id="foreign_in",
        display_name="In",
        django_representation="in",
        render_func=render_foreign_key_field
    )
    
    FOREIGN_ADVANCED = LookupDefinition(
        id="foreign_advanced",
        display_name="Advanced Lookup",
        django_representation="",
        render_func=render_advanced_lookup
    )
    
@dataclass
class FieldOption:
    id:str
    label:str
    primitive_input_type:Literal['text', 'number', 'bool', 'list']
    description:Optional[str] = None
    required: bool = False

NULL_FIELD_OPTION = FieldOption(
    "null",
    "Nullable",
    "bool",
    "Whether this field can be set to null"
)

BLANK_FIELD_OPTION = FieldOption(
    "blank",
    "Allow Empty Input",
    "bool",
    "Whether this field can be left empty in forms."
)

UNIQUE_FIELD_OPTION = FieldOption(
    "unique",
    "Unique",
    "bool",
    "Whether values for this field must be unique."
)

DB_INDEX_FIELD_OPTION = FieldOption(
    "db_index",
    "Indexed",
    "bool",
    "Whether to create a database index for this field."
)

DEFAULT_FIELD_OPTION = FieldOption(
    "default",
    "Default Value",
    "text",
    "Default value used when no value is provided."
)

HELP_TEXT_FIELD_OPTION = FieldOption(
    "help_text",
    "Help Text",
    "text",
    "Optional helper text shown to end users on forms."
)

MAX_LENGTH_FIELD_OPTION = FieldOption(
    "max_length",
    "Maximum Length",
    "number",
    "Maximum number of characters allowed.",
    required=True,
)

MAX_DIGITS_FIELD_OPTION = FieldOption(
    "max_digits",
    "Max Digits",
    "number",
    "Maximum number of digits stored by this decimal field.",
    required=True,
)

DECIMAL_PLACES_FIELD_OPTION = FieldOption(
    "decimal_places",
    "Decimal Places",
    "number",
    "Number of decimal places stored by this decimal field.",
    required=True,
)

UPLOAD_TO_FIELD_OPTION = FieldOption(
    "upload_to",
    "Upload Folder",
    "text",
    "Storage path prefix used when uploading files."
)

AUTO_NOW_FIELD_OPTION = FieldOption(
    "auto_now",
    "Auto Update On Save",
    "bool",
    "Automatically update this field to the current date/time on each save."
)

AUTO_NOW_ADD_FIELD_OPTION = FieldOption(
    "auto_now_add",
    "Auto Set On Create",
    "bool",
    "Automatically set this field to the current date/time when the object is created."
)

RELATED_NAME_FIELD_OPTION = FieldOption(
    "related_name",
    "Reverse Relation Name",
    "text",
    "Optional related_name used on the reverse side of relationships."
)

COMMON_FIELD_OPTIONS = [
    NULL_FIELD_OPTION,
    BLANK_FIELD_OPTION,
    UNIQUE_FIELD_OPTION,
    DB_INDEX_FIELD_OPTION,
    DEFAULT_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
]

COMMON_TEXT_FIELD_OPTIONS = [
    *COMMON_FIELD_OPTIONS,
    MAX_LENGTH_FIELD_OPTION,
]

COMMON_RELATION_FIELD_OPTIONS = [
    NULL_FIELD_OPTION,
    BLANK_FIELD_OPTION,
    RELATED_NAME_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
]

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
    
    lookups: list[Lookup] = dataclass_field(default_factory=list)
    allow_in_model: bool = True
    
    # Field options
    field_options: list[FieldOption] = dataclass_field(default_factory=list)

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

TEXT_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.IEXACT,
    Lookup.CONTAINS,
    Lookup.STARTS_WITH,
    Lookup.ENDS_WITH,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

NUMERIC_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.IN,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

DATE_LOOKUPS = [
    Lookup.EQUALS,
    Lookup.GREATER_THAN,
    Lookup.GREATER_THAN_OR_EQUAL,
    Lookup.LESS_THAN,
    Lookup.LESS_THAN_OR_EQUAL,
    Lookup.IS_NULL,
    Lookup.NOT_EQUALS,
]

BOOLEAN_LOOKUPS = [
    Lookup.EQUALS,
]

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
        field_options=COMMON_TEXT_FIELD_OPTIONS,
    )
    
    TEXT_FIELD = FieldTypeDefinition(
        id="TextField",
        display_name="Text Field",
        icon="fa-solid fa-paragraph",
        model_field_cls=models.TextField,
        lookups=TEXT_LOOKUPS,
        widget_cls=forms.Textarea,
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
        field_options=[
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DEFAULT_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
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
        field_options=COMMON_RELATION_FIELD_OPTIONS,
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
            BLANK_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ],
    )
    
    ONE_TO_MANY_FIELD = FieldTypeDefinition(
        id="OneToManyField",
        display_name="One To Many Field",
        icon="fa-solid fa-share-nodes",
        allow_in_model=False,
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
        field_options=COMMON_RELATION_FIELD_OPTIONS,
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
        for member in cls:
            if member.value.model_field_cls == model_field_cls:
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
        
            
