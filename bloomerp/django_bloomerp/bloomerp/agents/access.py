"""Agent-use authorization, separate from administrative row and field policies."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q, QuerySet

from bloomerp.models.agents.ai_agent import AIAgent
from bloomerp.models.users.user import AbstractBloomerpUser


class AIAgentAccessManager:
    """Resolve creator, direct-user, group, and administrator access to agents."""

    def __init__(self, user: AbstractBloomerpUser | AnonymousUser) -> None:
        """Retain the actor whose agent-use grants will be evaluated live."""
        self.user = user

    def get_accessible_queryset(self) -> QuerySet[AIAgent]:
        """Return agents the active actor may use, without exposing credentials."""
        query = AIAgent.objects.all()
        if not self.user.is_authenticated:
            return query.none()
        user = get_user_model().objects.filter(pk=self.user.pk, is_active=True).first()
        if user is None:
            return query.none()
        if user.is_superuser:
            return query
        grants = (
            Q(created_by_id=user.pk)
            | Q(access__users=user)
            | Q(access__groups__in=user.groups.all())
            | Q(access__all_authenticated_users=True)
        )
        if user.is_staff:
            grants |= Q(access__all_staff_users=True)
        return query.filter(grants).distinct()

    def can_use(self, agent: AIAgent) -> bool:
        """Check current grants for a persisted agent, including creator access."""
        return self.get_accessible_queryset().filter(pk=agent.pk).exists()
