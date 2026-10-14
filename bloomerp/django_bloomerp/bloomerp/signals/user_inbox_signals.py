"""Provision staff inboxes through the normal preference lifecycle."""

from functools import partial
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.preference_services import PreferenceManager


def _provision_staff_user_inbox(
    user_model: type[AbstractBloomerpUser],
    user_pk: Any,
    using: str,
) -> None:
    """Reload and lock the committed user before creating a missing inbox.

    Recheck staff status and inbox ownership because either can change between
    saving the user and committing the surrounding transaction. The preference
    manager retains the standard initial-default copy behavior.
    """
    with transaction.atomic(using=using):
        user = (
            user_model._default_manager.using(using)
            .select_for_update()
            .filter(pk=user_pk, is_staff=True)
            .first()
        )
        if user is None or Inbox.objects.filter(user=user).exists():
            return
        PreferenceManager(user).get_or_create_selected(Inbox)


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
    """Provision after the complete user transaction, including group writes.

    Raw fixture saves do not schedule work. Atomic Bloomerp forms and Django
    admin save many-to-many groups after the user row; waiting until commit
    lets group-shared initial defaults participate. Callers of a generic,
    non-atomic ModelForm must wrap both save and save_m2m in one transaction.
    In autocommit mode the callback runs immediately. A callback failure rolls
    back its inbox writes, but cannot roll back the already-committed user.
    """
    if raw:
        return

    transaction.on_commit(
        partial(_provision_staff_user_inbox, sender, instance.pk, using),
        using=using,
    )
