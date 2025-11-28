"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermission) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""
from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser
from enum import Enum
from bloomerp.models.auth import User
from bloomerp.constants.permissions import BasePermission
from django.db.models.query import QuerySet
from enum import Enum
from bloomerp.models import ApplicationField
from django.contrib.contenttypes.models import ContentType

# --------------------------
# Permission Definitions
# --------------------------
class BasePermissions(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    UPDATE = "update"
    
# --------------------------
# Service Functions
# --------------------------
def has_object_permission(user:User, object:Model, permission:BasePermission) -> bool:
    # TODO : Implement this function 
    return True


def has_access_to_object(user: AbstractBloomerpUser, obj: Model) -> bool:
    """Simple object level permission check."""
    if user.is_superuser:
        return True
    if hasattr(obj, "created_by"):
        return obj.created_by == user
    if hasattr(obj, "user"):
        return obj.user == user
    return True


def get_queryset_for_user(user: AbstractBloomerpUser, queryset:QuerySet[Model], permission: BasePermissions=BasePermissions.READ) -> QuerySet[Model]:
    """Filters a queryset based on the user's permissions."""
    return queryset


def has_access_to_field(user: AbstractBloomerpUser, field: ApplicationField) -> bool:
    """Checks if the user has access to a specific field."""
    # TODO: Placeholder function that checks if a user has access to a application field.
    
    return True
    
