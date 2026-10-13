"""Conversation access shared by HTTP components and messaging controllers."""

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet

from bloomerp.models.communication.instant_messaging import IMConversation
from bloomerp.models.users.user import AbstractBloomerpUser


class IMAccessManager:
    """Grant private conversation access through current staff membership only."""

    def __init__(self, user: AbstractBloomerpUser | AnonymousUser) -> None:
        """Bind access checks to the authenticated actor, never a supplied user ID."""
        self.user = user

    def get_conversations(self) -> QuerySet[IMConversation]:
        """Scope conversations to active membership, including for superusers."""
        if not self.user.is_authenticated or not self.user.is_active:
            return IMConversation.objects.none()
        from django.db.models import Q
        from bloomerp.communication.builtins.voip.access import VoIPAccessManager

        return IMConversation.objects.filter(
            participants__user=self.user, participants__left_at__isnull=True
        ).filter(
            Q(voip_number__isnull=True)
            | Q(voip_number__in=VoIPAccessManager(self.user).get_numbers(active=False))
        )

    def has_access_to_conversation(self, conversation: IMConversation) -> bool:
        """Check the same membership rule used to scope list and detail queries."""
        return self.get_conversations().filter(pk=conversation.pk).exists()
