"""Provision staff inboxes through the normal preference lifecycle."""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.preference_services import PreferenceManager


@receiver(
    post_save,
    sender=settings.AUTH_USER_MODEL,
    dispatch_uid="bloomerp.ensure_staff_user_inbox",
)
def ensure_staff_user_inbox(
    sender: type[AbstractBloomerpUser],
    instance: AbstractBloomerpUser,
    raw: bool,
    using: str,
    **kwargs: Any,
) -> None:
    """Ensure persisted staff users have an inbox without altering existing ones.

    Raw fixture saves must not query related tables. Lock the persisted user so
    overlapping user-save handlers cannot both provision an inbox, and read its
    staff flag rather than unsaved values left on a partially saved instance.
    The preference manager retains the standard initial-default copy behavior.
    """
    if raw:
        return

    with transaction.atomic(using=using):
        user = (
            sender._default_manager.using(using)
            .select_for_update()
            .filter(pk=instance.pk, is_staff=True)
            .first()
        )
        if user is None or Inbox.objects.filter(user=user).exists():
            return
        PreferenceManager(user).get_or_create_selected(Inbox)
