from dataclasses import dataclass, field as dataclass_field
import calendar
from typing import Literal, Optional, Callable, Any, Type
from functools import partial
from unittest.util import _MAX_LENGTH
from django.db import models
from enum import Enum
from django.forms import Widget
import django_filters
from bloomerp.form_fields.ordered_multiple_choice_field import OrderedMultipleChoiceField
from bloomerp.model_fields.user_field import UserField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django import forms
from bloomerp.widgets.ordered_field_select_widget import OrderedFieldSelectWidget
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget
from bloomerp.model_fields.address_field import AddressField
from bloomerp.model_fields.icon_field import IconField
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.form_fields.address_field import AddressFormField
from bloomerp.form_fields.icon_field import IconFormField
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.widgets.address_widget import AddressWidget
from bloomerp.widgets.icon_picker_widget import IconPickerWidget
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget
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

def render_hidden_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
    value: str = "true",
    helper_text: str = "This filter uses the current date automatically.",
) -> str:
    field_name = name_override or application_field.field
    return (
        f'<input type="hidden" name="{field_name}" value="{value}">'
        f'<div class="input w-full">{helper_text}</div>'
    )

def render_numeric_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
    min_value: int | None = None,
    max_value: int | None = None,
) -> str:
    field_name = name_override or application_field.field
    attrs = {"class": "input w-full"}
    if min_value is not None:
        attrs["min"] = min_value
    if max_value is not None:
        attrs["max"] = max_value
    return forms.NumberInput(attrs=attrs).render(name=field_name, value=None)


def render_month_lookup_value(
    application_field: "ApplicationField",
    name_override: Optional[str] = None,
) -> str:
    field_name = name_override or application_field.field
    return forms.Select(
        choices=[(str(index), calendar.month_name[index]) for index in range(1, 13)],
        attrs={"class": "select w-full"},
    ).render(name=field_name, value=None)

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

    TODAY = LookupDefinition(
        id="today",
        display_name="Today",
        django_representation="today",
        aliases=["__today"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses today's date automatically.",
        ),
    )

    YESTERDAY = LookupDefinition(
        id="yesterday",
        display_name="Yesterday",
        django_representation="yesterday",
        aliases=["__yesterday"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses yesterday's date automatically.",
        ),
    )

    THIS_WEEK = LookupDefinition(
        id="this_week",
        display_name="This Week",
        django_representation="this_week",
        aliases=["__this_week"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current week automatically.",
        ),
    )

    LAST_WEEK = LookupDefinition(
        id="last_week",
        display_name="Last Week",
        django_representation="last_week",
        aliases=["__last_week"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous week automatically.",
        ),
    )

    THIS_MONTH = LookupDefinition(
        id="this_month",
        display_name="This Month",
        django_representation="this_month",
        aliases=["__this_month"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current month automatically.",
        ),
    )

    LAST_MONTH = LookupDefinition(
        id="last_month",
        display_name="Last Month",
        django_representation="last_month",
        aliases=["__last_month"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous month automatically.",
        ),
    )

    THIS_QUARTER = LookupDefinition(
        id="this_quarter",
        display_name="This Quarter",
        django_representation="this_quarter",
        aliases=["__this_quarter"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current quarter automatically.",
        ),
    )

    LAST_QUARTER = LookupDefinition(
        id="last_quarter",
        display_name="Last Quarter",
        django_representation="last_quarter",
        aliases=["__last_quarter"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous quarter automatically.",
        ),
    )

    THIS_YEAR = LookupDefinition(
        id="this_year",
        display_name="This Year",
        django_representation="this_year",
        aliases=["__this_year"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the current year automatically.",
        ),
    )

    LAST_YEAR = LookupDefinition(
        id="last_year",
        display_name="Last Year",
        django_representation="last_year",
        aliases=["__last_year"],
        render_func=partial(
            render_hidden_lookup_value,
            helper_text="Uses the previous year automatically.",
        ),
    )

    YEAR = LookupDefinition(
        id="year",
        display_name="Year",
        django_representation="year",
        aliases=["__year"],
        render_func=partial(render_numeric_lookup_value, min_value=1),
    )

    MONTH = LookupDefinition(
        id="month",
        display_name="Month",
        django_representation="month",
        aliases=["__month"],
        render_func=render_month_lookup_value,
    )

    DAY = LookupDefinition(
        id="day",
        display_name="Day",
        django_representation="day",
        aliases=["__day"],
        render_func=partial(render_numeric_lookup_value, min_value=1, max_value=31),
    )

    WEEK = LookupDefinition(
        id="week",
        display_name="Week",
        django_representation="week",
        aliases=["__week"],
        render_func=partial(render_numeric_lookup_value, min_value=1, max_value=53),
    )
   
# -------------------------
# Field options
# ------------------------- 
@dataclass
class FieldOption:
    id: str
    label: str
    primitive_input_type: Literal['text', 'number', 'bool', 'list', 'model', 'choices', 'callable']
    description: Optional[str] = None
    required: bool = False
    default_value: Any = None
    choices: list[str] | None = None  # valid values when primitive_input_type='choices'
    mutually_exclusive_with: list[str] = dataclass_field(default_factory=list)
    python_type: Any = Any

    def __hash__(self) -> int:
        return hash(self.id)
    
NULL_FIELD_OPTION = FieldOption(
    id="null",
    label="Nullable",
    primitive_input_type="bool",
    description="Whether this field can be set to null",
    default_value=True,
    python_type=bool,
)

BLANK_FIELD_OPTION = FieldOption(
    id="blank",
    label="Allow Empty Input",
    primitive_input_type="bool",
    description="Whether this field can be left empty in forms.",
    default_value=True,
    python_type=bool,
)

UNIQUE_FIELD_OPTION = FieldOption(
    id="unique",
    label="Unique",
    primitive_input_type="bool",
    description="Whether values for this field must be unique.",
    default_value=False,
    python_type=bool,
)

DB_INDEX_FIELD_OPTION = FieldOption(
    id="db_index",
    label="Indexed",
    primitive_input_type="bool",
    description="Whether to create a database index for this field.",
    default_value=False,
    python_type=bool,
)

DEFAULT_FIELD_OPTION = FieldOption(
    id="default",
    label="Default Value",
    primitive_input_type="text",
    description="Default value used when no value is provided.",
    python_type=Any,
)

HELP_TEXT_FIELD_OPTION = FieldOption(
    id="help_text",
    label="Help Text",
    primitive_input_type="text",
    description="Optional helper text shown to end users on forms.",
    default_value="",
    python_type=str,
)

MAX_LENGTH_FIELD_OPTION = FieldOption(
    id="max_length",
    label="Maximum Length",
    primitive_input_type="number",
    description="Maximum number of characters allowed.",
    required=True,
    python_type=int,
)

MAX_DIGITS_FIELD_OPTION = FieldOption(
    id="max_digits",
    label="Max Digits",
    primitive_input_type="number",
    description="Maximum number of digits stored by this decimal field.",
    required=True,
    python_type=int,
)

DECIMAL_PLACES_FIELD_OPTION = FieldOption(
    id="decimal_places",
    label="Decimal Places",
    primitive_input_type="number",
    description="Number of decimal places stored by this decimal field.",
    required=True,
    python_type=int,
)

UPLOAD_TO_FIELD_OPTION = FieldOption(
    id="upload_to",
    label="Upload Folder",
    primitive_input_type="text",
    description="Storage path prefix used when uploading files.",
    default_value="",
    python_type=str,
)

AUTO_NOW_FIELD_OPTION = FieldOption(
    id="auto_now",
    label="Auto Update On Save",
    primitive_input_type="bool",
    description="Automatically update this field to the current date/time on each save.",
    default_value=False,
    mutually_exclusive_with=["auto_now_add"],
    python_type=bool,
)

AUTO_NOW_ADD_FIELD_OPTION = FieldOption(
    id="auto_now_add",
    label="Auto Set On Create",
    primitive_input_type="bool",
    description="Automatically set this field to the current date/time when the object is created.",
    default_value=False,
    mutually_exclusive_with=["auto_now"],
    python_type=bool,
)

RELATED_NAME_FIELD_OPTION = FieldOption(
    id="related_name",
    label="Reverse Relation Name",
    primitive_input_type="text",
    description="Optional related_name used on the reverse side of relationships.",
    python_type=str,
)

VERBOSE_NAME_FIELD_OPTION = FieldOption(
    id="verbose_name",
    label="Label",
    primitive_input_type="text",
    description="Human-readable name shown as the field label in forms and admin.",
    python_type=str,
)

TO_FIELD_OPTION = FieldOption(
    id="to",
    label="Related Model",
    primitive_input_type="model",
    description="The model this field points to.",
    required=True,
    python_type=type[models.Model] | str,
)

ON_DELETE_FIELD_OPTION = FieldOption(
    id="on_delete",
    label="On Delete Behaviour",
    primitive_input_type="choices",
    description="What happens to this object when the related object is deleted.",
    required=True,
    default_value="CASCADE",
    choices=["CASCADE", "PROTECT", "SET_NULL", "SET_DEFAULT", "DO_NOTHING"],
    python_type=Callable[..., Any],
)

CHOICES_FIELD_OPTION = FieldOption(
    id="choices",
    label="Choices",
    primitive_input_type="choices",
    description="Fixed options available for this field.",
    required=True,
    default_value=[],
    python_type=list[tuple[Any, Any]],
)

COMMON_FIELD_OPTIONS = [
    VERBOSE_NAME_FIELD_OPTION,
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

COMMON_CHOICE_FIELD_OPTIONS = [
    *COMMON_FIELD_OPTIONS,
    CHOICES_FIELD_OPTION,
    MAX_LENGTH_FIELD_OPTION,
]

COMMON_RELATION_FIELD_OPTIONS = [
    TO_FIELD_OPTION,
    VERBOSE_NAME_FIELD_OPTION,
    NULL_FIELD_OPTION,
    BLANK_FIELD_OPTION,
    DB_INDEX_FIELD_OPTION,
    RELATED_NAME_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
]

def _is_parent_link_field(application_field: "ApplicationField", parent_model: type[models.Model] | None) -> bool:
    if parent_model is None:
        return False
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    remote_field = getattr(model_field, "remote_field", None)
    return getattr(remote_field, "model", None) == parent_model


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


def get_related_model_field_choices(application_field: "ApplicationField") -> dict[str, Any]:
    from bloomerp.models import ApplicationField

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

@dataclass
class FieldDisplayOption:
    id: str
    label: str
    form_field_cls: type[forms.Field]
    required: bool = False
    default: Any = None
    help_text: str = ""
    form_field_kwargs: dict[str, Any] = dataclass_field(default_factory=dict)
    get_form_field_kwargs: Optional[Callable[["ApplicationField"], dict[str, Any]]] = None

    def build_form_field(self, application_field: "ApplicationField") -> forms.Field:
        kwargs = {
            "label": self.label,
            "required": self.required,
            "help_text": self.help_text,
            **self.form_field_kwargs,
        }
        if self.get_form_field_kwargs:
            kwargs.update(self.get_form_field_kwargs(application_field))
        return self.form_field_cls(**kwargs)
    


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
    Lookup.TODAY,
    Lookup.YESTERDAY,
    Lookup.THIS_WEEK,
    Lookup.LAST_WEEK,
    Lookup.THIS_MONTH,
    Lookup.LAST_MONTH,
    Lookup.THIS_QUARTER,
    Lookup.LAST_QUARTER,
    Lookup.THIS_YEAR,
    Lookup.LAST_YEAR,
    Lookup.YEAR,
    Lookup.MONTH,
    Lookup.DAY,
    Lookup.WEEK,
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
            *COMMON_RELATION_FIELD_OPTIONS,
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
        
            
