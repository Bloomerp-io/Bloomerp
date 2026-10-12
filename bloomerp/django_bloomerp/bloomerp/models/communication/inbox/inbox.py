from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Count, IntegerField, OuterRef, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user import AbstractBloomerpUser


class Inbox(BasePreference):
    """
    A selectable inbox owned by one user and optionally shared with others.

    Shared users select a lightweight ``BasePreference`` reference while folders
    and items remain attached to the owner's effective inbox.
    """
    class Meta:
        verbose_name_plural = _("Inboxes")
        verbose_name = _("Inbox")
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(selected=True),
                name="unique_selected_inbox_preference",
            ),
            models.UniqueConstraint(
                fields=["user", "source_object"],
                condition=models.Q(source_object__isnull=False),
                name="unique_inbox_preference_reference",
            ),
        ]

    bloomerp_config = BasePreference.bloomerp_config.model_copy(
        update={"module": "communication"},
    )

    force_copy_initial_default = True

    @classmethod
    def create_default_for_user(
        cls,
        user: AbstractBloomerpUser,
        **scope,
    ) -> "Inbox":
        """Create and select a default inbox with its standard folders."""
        from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
        from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

        with transaction.atomic():
            inbox = cls.objects.create(
                user=user,
                name="My Inbox",
                selected=True,
            )
            InboxFolder.objects.bulk_create(
                [
                    InboxFolder(
                        inbox=inbox,
                        type=folder_type.key,
                    )
                    for folder_type in INBOX_FOLDER_REGISTRY.values()
                    if folder_type.is_default
                ]
            )
        return inbox

    @classmethod
    def copy_preference_for_user(
        cls,
        *,
        user: AbstractBloomerpUser,
        source: "Inbox",
        name: str,
        scope: dict | None = None,
    ) -> "Inbox":
        """Copy an Inbox shell and its default folders, excluding all items."""
        from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

        with transaction.atomic():
            inbox = cls._create_preference_copy(
                user=user,
                source=source,
                name=name,
                scope=scope,
            )
            InboxFolder.objects.bulk_create(
                [
                    InboxFolder(
                        type=folder.type,
                        inbox=inbox,
                    )
                    for folder in source.folders.all()
                    if folder.inbox_folder_type().is_default
                ]
            )
        return inbox

    def get_unread_count(self):
        """
        Returns the count of unread items in the inbox.
        """
        from bloomerp.models.communication.inbox.inbox_item import InboxItem

        return (
            InboxItem.objects
            .filter(folder__inbox=self.effective_preference, is_read=False)
            .distinct()
            .count()
        )

    def __str__(self) -> str:
        return self.effective_preference.name

    @staticmethod
    def get_unread_count_for_user(
        user: int | str | AbstractBloomerpUser,
    ) -> int:
        """Return one user's selected effective Inbox unread count."""
        user_id = user.pk if isinstance(user, AbstractBloomerpUser) else user
        return Inbox.get_unread_count_for_users([user_id]).get(str(user_id), 0)

    @staticmethod
    def get_unread_count_for_users(
        users: list[int | str] | QuerySet[AbstractBloomerpUser],
    ) -> dict[str, int]:
        """Return each user's selected effective Inbox unread count in one query.

        Args:
            users: User IDs or a user queryset to include.

        Returns:
            A mapping of stringified user IDs to unread counts. Users without a
            selected Inbox are included with a count of zero.
        """
        from bloomerp.models.communication.inbox.inbox_item import InboxItem

        user_model = get_user_model()
        if isinstance(users, QuerySet):
            requested_user_ids = users.values("pk")
        else:
            requested_user_ids = users

        selected_effective_inbox = (
            Inbox.objects.filter(
                user_id=OuterRef("pk"),
                selected=True,
            )
            .annotate(
                effective_inbox_id=Coalesce(
                    "source_object_id",
                    "pk",
                )
            )
            .values("effective_inbox_id")[:1]
        )
        unread_items = (
            InboxItem.objects.filter(
                folder__inbox_id=OuterRef("effective_inbox_id"),
                is_read=False,
            )
            .values("folder__inbox_id")
            .annotate(total=Count("pk"))
            .values("total")[:1]
        )
        users_with_counts = (
            user_model.objects.filter(pk__in=requested_user_ids)
            .annotate(
                effective_inbox_id=Subquery(selected_effective_inbox),
            )
            .annotate(
                unread_count=Coalesce(
                    Subquery(unread_items, output_field=IntegerField()),
                    Value(0),
                )
            )
        )

        return {
            str(user_id): unread_count
            for user_id, unread_count in users_with_counts.values_list(
                "pk",
                "unread_count",
            )
        }
