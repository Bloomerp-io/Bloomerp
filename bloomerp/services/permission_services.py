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
