"""Agent-use authorization, separate from administrative row and field policies."""

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
        if not self.user.is_authenticated or not self.user.is_active:
            return query.none()
        if self.user.is_superuser:
            return query
        return query.filter(
            Q(created_by_id=self.user.pk)
            | Q(access__users=self.user)
            | Q(access__groups__in=self.user.groups.all())
        ).distinct()

    def can_use(self, agent: AIAgent) -> bool:
        """Check current grants for a persisted agent, including creator access."""
        return self.get_accessible_queryset().filter(pk=agent.pk).exists()
