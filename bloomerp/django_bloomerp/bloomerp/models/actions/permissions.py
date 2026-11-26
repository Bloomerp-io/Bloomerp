from django.db.models import Model
from django.http import HttpRequest

from bloomerp.permissions.definition import BloomerpPermission


def can_add_model(request: HttpRequest, model: type[Model]) -> bool:
    """Reuse a model's add permission across actions rendered in one request."""
    from bloomerp.permissions.manager import UserPolicyManager

    cache = getattr(request, "_bloomerp_action_add_permissions", None)
    if cache is None:
        cache = {}
        request._bloomerp_action_add_permissions = cache
    if model not in cache:
        cache[model] = UserPolicyManager(request.user).has_global_permission(
            model, BloomerpPermission.ADD,
        )
    return cache[model]
