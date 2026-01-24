from dataclasses import dataclass, field as dataclass_field
from typing import Optional, Callable, Any
from colorama import Fore
from django.db import models
from enum import Enum
from django.forms import CharField
import django_filters
from bloomerp.model_fields.user_field import UserField
from bloomerp.widgets.foreign_key_widget import ForeignFieldWidget


def render_foreign_key_field(application_field:"ApplicationField") -> str:
    return ForeignFieldWidget(model=application_field.get_related_model()).render(
        name=application_field.field,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
    
def render_foreign_key_in(application_field:"ApplicationField") -> str:
    return ForeignFieldWidget(model=application_field.get_related_model()).render(
        name=application_field.field,
        value=None,
        attrs={
            "class": "input w-full"
        }
    )
    


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
    
    def render(self, application_field) -> str:
        if not self.render_func:
            return """<input type="text" class="input">"""

        return self.render_func(application_field)
        
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
        django_representation="exact",
    )
    
    FOREIGN_EQUALS = LookupDefinition(
        id="foreign_equals",
        display_name="Equals",
        django_representation="",
        render_func=render_foreign_key_field
    )
    
    FOREIGN_IN = LookupDefinition(
        id="foreign_in",
        display_name="In",
        django_representation="",
        render_func=render_foreign_key_field
    )
    
    

@dataclass(frozen=True)
class FieldTypeDefinition:
    """Definition of a field type with its metadata."""
    id: str  # Internal ID used for lookup (e.g., "ForeignKey")
    display_name: str  # Human-readable name
    django_field_class: Optional[type[models.Field]] = None
    description: Optional[str] = None
    lookups: list[Lookup] = dataclass_field(default_factory=list)


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
        field_type.django_field_class  # models.ForeignKey
    """
    
    # Basic Fields
    PROPERTY = FieldTypeDefinition(
        id="Property",
        display_name="Property"
    )
    
    AUTO_FIELD = FieldTypeDefinition(
        id="AutoField",
        display_name="Auto Field",
        django_field_class=models.AutoField,
        lookups=NUMERIC_LOOKUPS,
    )
    
    BIG_AUTO_FIELD = FieldTypeDefinition(
        id="BigAutoField",
        display_name="Big Auto Field",
        django_field_class=models.BigAutoField,
        lookups=NUMERIC_LOOKUPS,
    )
    
    SMALL_AUTO_FIELD = FieldTypeDefinition(
        id="SmallAutoField",
        display_name="Small Auto Field",
        django_field_class=models.SmallAutoField,
        lookups=NUMERIC_LOOKUPS,
    )
    
    # Text Fields
    CHAR_FIELD = FieldTypeDefinition(
        id="CharField",
        display_name="Char Field",
        django_field_class=models.CharField,
        lookups=TEXT_LOOKUPS
    )
    
    TEXT_FIELD = FieldTypeDefinition(
        id="TextField",
        display_name="Text Field",
        django_field_class=models.TextField,
        lookups=TEXT_LOOKUPS
    )
    
    EMAIL_FIELD = FieldTypeDefinition(
        id="EmailField",
        display_name="Email Field",
        django_field_class=models.EmailField,
        lookups=TEXT_LOOKUPS
    )
    
    URL_FIELD = FieldTypeDefinition(
        id="URLField",
        display_name="URL Field",
        django_field_class=models.URLField,
        lookups=TEXT_LOOKUPS
    )
    
    SLUG_FIELD = FieldTypeDefinition(
        id="SlugField",
        display_name="Slug Field",
        django_field_class=models.SlugField,
        lookups=TEXT_LOOKUPS
    )
    
    # Numeric Fields
    INTEGER_FIELD = FieldTypeDefinition(
        id="IntegerField",
        display_name="Integer Field",
        django_field_class=models.IntegerField,
        lookups=NUMERIC_LOOKUPS
    )
    
    FLOAT_FIELD = FieldTypeDefinition(
        id="FloatField",
        display_name="Float Field",
        django_field_class=models.FloatField,
        lookups=NUMERIC_LOOKUPS
    )
    
    DECIMAL_FIELD = FieldTypeDefinition(
        id="DecimalField",
        display_name="Decimal Field",
        django_field_class=models.DecimalField,
        lookups=NUMERIC_LOOKUPS
    )
    
    POSITIVE_INTEGER_FIELD = FieldTypeDefinition(
        id="PositiveIntegerField",
        display_name="Positive Integer Field",
        django_field_class=models.PositiveIntegerField,
        lookups=NUMERIC_LOOKUPS
    )
    
    POSITIVE_SMALL_INTEGER_FIELD = FieldTypeDefinition(
        id="PositiveSmallIntegerField",
        display_name="Positive Small Integer Field",
        django_field_class=models.PositiveSmallIntegerField,
        lookups=NUMERIC_LOOKUPS
    )
    
    BIG_INTEGER_FIELD = FieldTypeDefinition(
        id="BigIntegerField",
        display_name="Big Integer Field",
        django_field_class=models.BigIntegerField,
        lookups=NUMERIC_LOOKUPS
    )
    
    SMALL_INTEGER_FIELD = FieldTypeDefinition(
        id="SmallIntegerField",
        display_name="Small Integer Field",
        django_field_class=models.SmallIntegerField,
        lookups=NUMERIC_LOOKUPS
    )
    
    # Boolean Fields
    BOOLEAN_FIELD = FieldTypeDefinition(
        id="BooleanField",
        display_name="Boolean Field",
        django_field_class=models.BooleanField,
        lookups=BOOLEAN_LOOKUPS
    )
    
    NULL_BOOLEAN_FIELD = FieldTypeDefinition(
        id="NullBooleanField",
        display_name="Null Boolean Field",
        lookups=BOOLEAN_LOOKUPS
    )
    
    # Date/Time Fields  
    DATE_FIELD = FieldTypeDefinition(
        id="DateField",
        display_name="Date Field",
        django_field_class=models.DateField,
        lookups=DATE_LOOKUPS,
    )
    
    DATE_TIME_FIELD = FieldTypeDefinition(
        id="DateTimeField",
        display_name="DateTime Field",
        django_field_class=models.DateTimeField,
        lookups=DATE_LOOKUPS,
    )
    
    TIME_FIELD = FieldTypeDefinition(
        id="TimeField",
        display_name="Time Field",
        django_field_class=models.TimeField,
        lookups=DATE_LOOKUPS
    )
    
    DURATION_FIELD = FieldTypeDefinition(
        id="DurationField",
        display_name="Duration Field",
        django_field_class=models.DurationField,
        lookups=NUMERIC_LOOKUPS
    )
    
    # File Fields
    FILE_FIELD = FieldTypeDefinition(
        id="FileField",
        display_name="File Field",
        django_field_class=models.FileField,
    )
    
    IMAGE_FIELD = FieldTypeDefinition(
        id="ImageField",
        display_name="Image Field",
        django_field_class=models.ImageField,
        
    )
    
    # Relationship Fields
    FOREIGN_KEY = FieldTypeDefinition(
        id="ForeignKey",
        display_name="Foreign Key",
        django_field_class=models.ForeignKey,
        lookups=[
            Lookup.FOREIGN_EQUALS,
            Lookup.FOREIGN_IN,
        ],
    )
    
    ONE_TO_ONE_FIELD = FieldTypeDefinition(
        id="OneToOneField",
        display_name="One To One Field",
        django_field_class=models.OneToOneField,
        lookups=[
            Lookup.IS_NULL,
            Lookup.EQUALS,
            Lookup.IN,
        ],
    )
    
    MANY_TO_MANY_FIELD = FieldTypeDefinition(
        id="ManyToManyField",
        display_name="Many To Many Field",
        django_field_class=models.ManyToManyField,
        lookups=[
            Lookup.EQUALS,
            Lookup.IS_NULL,
            Lookup.IN,
        ],
    )
    
    ONE_TO_MANY_FIELD = FieldTypeDefinition(
        id="OneToManyField",
        display_name="One To Many Field"
    )
    
    USER_FIELD = FieldTypeDefinition(
        id="UserField",
        display_name="User Field",
        django_field_class=UserField,
        lookups=[
            Lookup.IS_NULL,
            Lookup.FOREIGN_IN,
            Lookup.EQUALS_USER,
            Lookup.FOREIGN_EQUALS
        ],
    )
    
    # Other Fields
    UUID_FIELD = FieldTypeDefinition(
        id="UUIDField",
        display_name="UUID Field",
        django_field_class=models.UUIDField,
        lookups=[Lookup.EQUALS, Lookup.IN, Lookup.IS_NULL]
    )
    BINARY_FIELD = FieldTypeDefinition(
        id="BinaryField",
        display_name="Binary Field",
        django_field_class=models.BinaryField,
        
    )
    IP_ADDRESS_FIELD = FieldTypeDefinition(
        id="IPAddressField",
        display_name="IP Address Field",
        lookups=TEXT_LOOKUPS
    )
    
    GENERIC_IP_ADDRESS_FIELD = FieldTypeDefinition(
        id="GenericIPAddressField",
        display_name="Generic IP Address Field",
        django_field_class=models.GenericIPAddressField,
        lookups=TEXT_LOOKUPS
    )
    
    JSON_FIELD = FieldTypeDefinition(
        id="JSONField",
        display_name="JSON Field",
        django_field_class=models.JSONField,
        
    )
    
    ARRAY_FIELD = FieldTypeDefinition(
        id="ArrayField",
        display_name="Array Field",
        lookups=[Lookup.CONTAINS, Lookup.IS_NULL]
    )
    
    HSTORE_FIELD = FieldTypeDefinition(
        id="HStoreField",
        display_name="HStore Field",
        
    )
    
    # Generic Relations
    GENERIC_RELATION = FieldTypeDefinition(
        id="GenericRelation",
        display_name="Generic Relation",
        
    )
    GENERIC_FOREIGN_KEY = FieldTypeDefinition(
        id="GenericForeignKey",
        display_name="Generic Foreign Key",
        
    )
    
    # Custom Bloomerp Fields
    STATUS_FIELD = FieldTypeDefinition(
        id="StatusField",
        display_name="Status Field",
        lookups=TEXT_LOOKUPS
    )
    BLOOMERP_FILE_FIELD = FieldTypeDefinition(
        id="BloomerpFileField",
        display_name="Bloomerp File Field",
        
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
    def django_field_class(self) -> Optional[type[models.Field]]:
        """Returns the Django field class, if applicable."""
        return self.value.django_field_class
    
    @property
    def lookups(self) -> list[Lookup]:
        """Returns the list of supported lookups for this field type."""
        return self.value.lookups
    
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
    def from_django_field_class(cls, django_field_class: type[models.Field]) -> Optional["FieldType"]:
        """Get a FieldType by its Django field class.
        
        Args:
            django_field_class: The Django field class (e.g., models.ForeignKey)
            
        Returns:
            The matching FieldType enum member, or None if not found
        """
        for member in cls:
            if member.value.django_field_class == django_field_class:
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
        

