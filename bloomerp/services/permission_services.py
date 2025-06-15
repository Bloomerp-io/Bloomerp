from django.db.models import Model
from bloomerp.models import AbstractBloomerpUser


def has_access_to_object(user: AbstractBloomerpUser, obj: Model) -> bool:
    """Simple object level permission check."""
    if user.is_superuser:
        return True
    if hasattr(obj, "created_by"):
        return obj.created_by == user
    if hasattr(obj, "user"):
        return obj.user == user
    return True
