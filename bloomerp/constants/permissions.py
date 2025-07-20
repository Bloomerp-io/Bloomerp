from enum import Enum

class BasePermission(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    UPDATE = "update"
    
    def __str__(self):
        return self.value
