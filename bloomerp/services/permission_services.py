from enum import Enum
"""
This module provides services related to permissions management.
Classes:
    BasePermissions (Enum): Defines basic permission types such as READ, WRITE, DELETE, and UPDATE.
Functions:
    has_object_permission(user: User, permission: BasePermissions) -> bool:
        Checks if the given user has the specified object-level permission.
"""

"""Services regarding permissions"""

class BasePermissions(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    UPDATE = "update"
    
    def __str__(self):
        return self.value

def has_object_permission(user:User, permission:BasePermissions) -> bool:
    pass