from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.db.models.query import QuerySet
from bloomerp.models.base_bloomerp_model import BloomerpModel
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from django.utils.translation import gettext_lazy as _

@dataclass(frozen=True)
class FieldTypeDefinition:
    """Definition of a field type with its metadata."""
    id: str  # Internal ID used for lookup (e.g., "ForeignKey")
    display_name: str  # Human-readable name
    django_field_class: Optional[type[models.Field]] = None


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
    PROPERTY = FieldTypeDefinition("Property", "Property")
    AUTO_FIELD = FieldTypeDefinition("AutoField", "Auto Field", models.AutoField)
    BIG_AUTO_FIELD = FieldTypeDefinition("BigAutoField", "Big Auto Field", models.BigAutoField)
    SMALL_AUTO_FIELD = FieldTypeDefinition("SmallAutoField", "Small Auto Field", models.SmallAutoField)
    
    # Text Fields
    CHAR_FIELD = FieldTypeDefinition("CharField", "Char Field", models.CharField)
    TEXT_FIELD = FieldTypeDefinition("TextField", "Text Field", models.TextField)
    EMAIL_FIELD = FieldTypeDefinition("EmailField", "Email Field", models.EmailField)
    URL_FIELD = FieldTypeDefinition("URLField", "URL Field", models.URLField)
    SLUG_FIELD = FieldTypeDefinition("SlugField", "Slug Field", models.SlugField)
    
    # Numeric Fields
    INTEGER_FIELD = FieldTypeDefinition("IntegerField", "Integer Field", models.IntegerField)
    FLOAT_FIELD = FieldTypeDefinition("FloatField", "Float Field", models.FloatField)
    DECIMAL_FIELD = FieldTypeDefinition("DecimalField", "Decimal Field", models.DecimalField)
    POSITIVE_INTEGER_FIELD = FieldTypeDefinition("PositiveIntegerField", "Positive Integer Field", models.PositiveIntegerField)
    POSITIVE_SMALL_INTEGER_FIELD = FieldTypeDefinition("PositiveSmallIntegerField", "Positive Small Integer Field", models.PositiveSmallIntegerField)
    BIG_INTEGER_FIELD = FieldTypeDefinition("BigIntegerField", "Big Integer Field", models.BigIntegerField)
    SMALL_INTEGER_FIELD = FieldTypeDefinition("SmallIntegerField", "Small Integer Field", models.SmallIntegerField)
    
    # Boolean Fields
    BOOLEAN_FIELD = FieldTypeDefinition("BooleanField", "Boolean Field", models.BooleanField)
    NULL_BOOLEAN_FIELD = FieldTypeDefinition("NullBooleanField", "Null Boolean Field")
    
    # Date/Time Fields  
    DATE_FIELD = FieldTypeDefinition("DateField", "Date Field", models.DateField)
    DATE_TIME_FIELD = FieldTypeDefinition("DateTimeField", "DateTime Field", models.DateTimeField)
    TIME_FIELD = FieldTypeDefinition("TimeField", "Time Field", models.TimeField)
    DURATION_FIELD = FieldTypeDefinition("DurationField", "Duration Field", models.DurationField)
    
    # File Fields
    FILE_FIELD = FieldTypeDefinition("FileField", "File Field", models.FileField)
    IMAGE_FIELD = FieldTypeDefinition("ImageField", "Image Field", models.ImageField)
    
    # Relationship Fields
    FOREIGN_KEY = FieldTypeDefinition("ForeignKey", "Foreign Key", models.ForeignKey)
    ONE_TO_ONE_FIELD = FieldTypeDefinition("OneToOneField", "One To One Field", models.OneToOneField)
    MANY_TO_MANY_FIELD = FieldTypeDefinition("ManyToManyField", "Many To Many Field", models.ManyToManyField)
    ONE_TO_MANY_FIELD = FieldTypeDefinition("OneToManyField", "One To Many Field")
    
    # Other Fields
    UUID_FIELD = FieldTypeDefinition("UUIDField", "UUID Field", models.UUIDField)
    BINARY_FIELD = FieldTypeDefinition("BinaryField", "Binary Field", models.BinaryField)
    IP_ADDRESS_FIELD = FieldTypeDefinition("IPAddressField", "IP Address Field")
    GENERIC_IP_ADDRESS_FIELD = FieldTypeDefinition("GenericIPAddressField", "Generic IP Address Field", models.GenericIPAddressField)
    JSON_FIELD = FieldTypeDefinition("JSONField", "JSON Field", models.JSONField)
    ARRAY_FIELD = FieldTypeDefinition("ArrayField", "Array Field")
    HSTORE_FIELD = FieldTypeDefinition("HStoreField", "HStore Field")
    
    # Generic Relations
    GENERIC_RELATION = FieldTypeDefinition("GenericRelation", "Generic Relation")
    GENERIC_FOREIGN_KEY = FieldTypeDefinition("GenericForeignKey", "Generic Foreign Key")
    
    # Custom Bloomerp Fields
    STATUS_FIELD = FieldTypeDefinition("StatusField", "Status Field")
    BLOOMERP_FILE_FIELD = FieldTypeDefinition("BloomerpFileField", "Bloomerp File Field")

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


class ApplicationField(models.Model):
    """
    An ApplicationField is a model that stores information 
    about fields and attributes in the Django model.
    
    It is used throughout the application to provide metadata
    about fields, such as their type, related model (if any),
    and other useful information.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_application_field"

    allow_string_search = False

    field = models.CharField(
        max_length=100,
        help_text=_("The name of the field.")
        )
    content_type = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        help_text=_("The content type (model) this field belongs to.")
        )
    field_type = models.CharField(
        max_length=100, 
        choices=FieldType.choices(),
        help_text=_("The type of the field.")
        )
    related_model = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='related_models', 
        help_text=_("Related model for ForeignKey, OneToOneField, ManyToManyField")
        )
    meta = models.JSONField(
        null=True, 
        blank=True,
        help_text=_("Additional metadata about the field.")
        )

    # Database related fields
    db_table = models.CharField(
        max_length=100, 
        null=True, 
        blank=True,
        help_text=_("The database table this field belongs to.")
    )
    db_field_type = models.CharField(
        max_length=100, 
        null=True, 
        blank=True)
    db_column = models.CharField(
        max_length=100, 
        null=True, 
        blank=True
        )

    def __str__(self):
        return self.content_type.__str__() + " | " + str(self.field)

    def get_field_type_enum(self) -> FieldType:
        """Returns the FieldType enum for this application field."""
        return FieldType.from_id(self.field_type)

    def get_for_model(model:models.Model) -> QuerySet:
        """Returns application fields for a specific model"""
        return ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(model)
        )

    @property
    def title(self):
        return self.field.replace("_", " ").title()

    @staticmethod
    def get_related_models(model: models.Model, skip_auto_created=True):
        """Returns all related models for a specific model"""
        content_type_id = ContentType.objects.get_for_model(model).pk
        qs = ApplicationField.objects.filter(
            meta__related_model=content_type_id
        ).exclude(content_type=content_type_id)
        if skip_auto_created:
            qs = qs.exclude(meta__auto_created=True)

        return qs

    @staticmethod
    def get_db_tables_and_columns(user= None) -> list[tuple[str, list[str]]]:
        """
        Returns a tuple for each database table.
        The tuple contains the table name and a tuple of the list of columns and there datatype.
        
        Args:
            user (User): The user object


        Example output:
        [
            ('auth_user', [('id', 'int'), ('username','varchar'), ...]),
            ('auth_group', [('id', 'int'), ('name','varchar'), ...]),
        ]

        """
        tables = []

        qs = ApplicationField.objects.filter(db_table__isnull=False)

        if user:
            content_types = user.get_content_types_for_user(permission_types=["view"])
            qs = qs.filter(content_type__in=content_types)


        for table in qs.values("db_table").distinct():
            table_name = table["db_table"]
            columns = ApplicationField.objects.filter(db_table=table_name).values_list(
                "db_column", "db_field_type"
            )
            tables.append((table_name, columns))
        return tables

