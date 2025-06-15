"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermissions) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""
from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser
from enum import Enum
from bloomerp.models.auth import User

class BasePermissions(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    UPDATE = "update"
    
    def __str__(self):
        return self.value

def has_object_permission(user:User, permission:BasePermissions) -> bool:
    pass


def has_access_to_object(user: AbstractBloomerpUser, obj: Model) -> bool:
    """Simple object level permission check."""
    if user.is_superuser:
        return True
    if hasattr(obj, "created_by"):
        return obj.created_by == user
    if hasattr(obj, "user"):
        return obj.user == user
    return True
