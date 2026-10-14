"""Enforce provider-declared line assignment limits on every M2M add path."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils.translation import gettext as _

from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY
from bloomerp.models.communication.voip import VoIPNumber


@receiver(
    m2m_changed,
    sender=VoIPNumber.assigned_users.through,
    dispatch_uid="bloomerp.voip_assignment_limit",
)
def validate_line_assignments(
    sender: type[models.Model],
    instance: models.Model,
    action: str,
    reverse: bool,
    model: type[models.Model],
    pk_set: set[Any] | None,
    using: str,
    **kwargs: Any,
) -> None:
    """Lock affected lines and reject additions beyond their provider's user limit."""
    if action != "pre_add" or not pk_set:
        return
    numbers = VoIPNumber.objects.using(using).select_for_update().order_by("pk")
    numbers = numbers.filter(pk__in=pk_set) if reverse else numbers.filter(pk=instance.pk)
    for number in numbers:
        provider = VOIP_PROVIDER_REGISTRY.get(number.connection.provider)
        limit = provider.max_assigned_users if provider else None
        if limit is None:
            continue
        assigned = set(number.assigned_users.using(using).values_list("pk", flat=True))
        additions = {instance.pk} if reverse else pk_set
        if len(assigned | additions) > limit:
            raise ValidationError(
                {
                    "assigned_users": _(
                        "%(provider)s lines allow at most %(limit)s assigned users."
                    ) % {"provider": provider.display_name, "limit": limit}
                }
            )
