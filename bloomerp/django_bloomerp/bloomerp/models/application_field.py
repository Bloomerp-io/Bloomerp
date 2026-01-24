from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.db.models.query import QuerySet
from bloomerp.models.base_bloomerp_model import BloomerpModel
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from django.utils.translation import gettext_lazy as _
from bloomerp.field_types import FieldType

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

    @staticmethod
    def get_for_content_type_id(content_type_id: int) -> QuerySet:
        """Retrieves the application fields for a particular content type ID.

        Args:
            content_type_id (int): the content type ID

        Returns:
            QuerySet: the application fields
        """
        return ApplicationField.objects.filter(
            content_type_id=content_type_id
        )

    def get_model(self) -> models.Model:
        """Returns the model class for this application field."""
        return self.content_type.model_class()
    
    def get_related_model(self) -> Optional[models.Model]:
        """Returns the related model class for this application field, if any."""
        if self.related_model:
            return self.related_model.model_class()
        return None
    