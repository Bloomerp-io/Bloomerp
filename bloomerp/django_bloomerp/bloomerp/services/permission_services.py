"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermission) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""
from django.db import models
from django.db.models import Model
from bloomerp.models.users.user import AbstractBloomerpUser, User
from enum import Enum
from bloomerp.constants.permissions import BasePermission
from django.db.models.query import QuerySet
from enum import Enum
from bloomerp.models import ApplicationField
from django.db.models import QuerySet
from bloomerp.models.access_control import Policy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.row_policy import RowPolicy
from django.contrib.contenttypes.models import ContentType
from typing import Type
    
# --------------------------
# Service Functions
# --------------------------
def create_permission_str(obj_or_model: Model, permission: str) -> str:
    """Creates a permission string using an object or model.

    Args:
        obj_or_model (Model) : an object or model
        permission (str) : the permission
    """
    return f"{permission}_{obj_or_model._meta.model_name}"
    

class UserPermissionManager:
    policies : QuerySet[Policy]
    
    def __init__(self, user: AbstractBloomerpUser):
        self.user = user
        self.policies = self.get_user_policies()
    
    def get_user_policies(self) -> QuerySet[Policy]:
        """Retrieve all policies associated with the user.

        Returns:
            QuerySet[Policy]: queryset of policies linked to the user.
        """
        if not self.user:
            return Policy.objects.none()

        return (
            Policy.objects.filter(
                models.Q(users=self.user) | models.Q(groups__in=self.user.groups.all())
            )
            .distinct()
        )
        
    def get_field_policies(self) -> QuerySet[FieldPolicy]:
        """Retrieve field policies associated with the user.
        
        Returns:
            QuerySet[FieldPolicy]: queryset of field policies linked to the user.
        """
        return FieldPolicy.objects.filter(
            policies__in=self.policies
        ).distinct()
    
    def get_row_policies(self) -> QuerySet[RowPolicy]:
        """Retrieve row policies associated with the user.

        Returns:
            QuerySet[RowPolicy]: queryset of row policies linked to the user.
        """
        return (
            RowPolicy.objects.filter(
                policies__in=self.policies
            )
            .prefetch_related("rules__permissions")
            .distinct()
        )
    
    def has_global_permission(self, model : models.Model, permission_str) -> bool:
        pass
    
    def has_field_permission(self, field: ApplicationField, permission_str:str) -> bool:
        pass
    
    def get_accessible_fields(self, model_or_content_type: models.Model | ContentType, permission_str:str) -> QuerySet[ApplicationField]:
        """Returns the application fields with a certain permission.

        Args:
            model_or_content_type (models.Model | ContentType): The model or content type to check fields for.
            permission_str (str): The permission string to check.

        Returns:
            QuerySet[ApplicationField]: Queryset of application fields with the specified permission.
        """
        if not model_or_content_type:
            return ApplicationField.objects.none()

        if isinstance(model_or_content_type, models.Model):
            content_type = ContentType.objects.get_for_model(model_or_content_type)
        else:
            content_type = model_or_content_type    
        
        # Return all fields if user is superuser
        if self.user.is_superuser:
            return ApplicationField.objects.filter(content_type=content_type)
        
        permission_value = str(permission_str)

        policies = self.get_field_policies().filter(content_type=content_type)
        
        if not policies.exists():
            return ApplicationField.objects.none()

        allowed_field_ids: set[str] = set()

        for policy in policies:
            rules = policy.rule or {}
            if not isinstance(rules, dict):
                continue

            for field_id, permissions in rules.items():
                if not isinstance(permissions, list):
                    continue
                if permission_value not in permissions:
                    continue

                if field_id == "__all__":
                    return ApplicationField.objects.filter(content_type=content_type)

                allowed_field_ids.add(str(field_id))

        if not allowed_field_ids:
            return ApplicationField.objects.none()

        return ApplicationField.objects.filter(
            content_type=content_type,
            id__in=allowed_field_ids
        )
        
    def has_access_to_object(self, object:models.Model) -> bool:
        """Returns a boolean that checks whether a user has access to a particular object

        Args:
            object (models.Model): the django ORM object

        Returns:
            bool: whether the user has access to the object
        """
        
        return True
    
    def get_queryset(self, model_or_content_type:Type[models.Model]|ContentType, permission_str:str) -> QuerySet[models.Model]:
        """Returns the queryset for a particular model that the user has access to

        Args:
            model_or_content_type (models.Model | ContentType): the model or 

        Returns:
            QuerySet[models.Model]: _description_
        """
        if isinstance(model_or_content_type, ContentType):
            model = model_or_content_type.model_class()
        elif issubclass(model_or_content_type, models.Model):
            model = model_or_content_type
        else:
            raise TypeError(f"Wrong type")
        
        return model.objects.all()