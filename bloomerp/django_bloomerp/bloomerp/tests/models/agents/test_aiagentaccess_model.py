"""Declarative audience grants retain deny-by-default agent configuration."""

from typing import Any

from django.contrib.auth.models import AnonymousUser

from bloomerp.agents.access import AIAgentAccessManager
from bloomerp.models import User
from bloomerp.models.agents import AIAgent, AIAgentAccess
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario


class TestAIAgentAccessModel(BloomerpModelTestCase):
    """Cover flags as additive grants with current active account attributes."""

    model = AIAgentAccess

    def prepare_actors(self) -> None:
        """Create a creator, staff actor, ordinary member and inactive staff actor."""
        self.creator = User.objects.create_user(username="audience-creator")
        self.staff = User.objects.create_user(username="audience-staff", is_staff=True)
        self.member = User.objects.create_user(username="audience-member")
        self.inactive = User.objects.create_user(
            username="audience-inactive", is_staff=True, is_active=False
        )
        self.agent = AIAgent.objects.create(
            name="Audience agent",
            provider="openai",
            model_identifier="offline",
            created_by=self.creator,
        )

    def grant_args(self) -> dict[str, Any]:
        """Supply the required framework model fields without broad grants."""
        return {"name": "Audience", "model": self.agent}

    def get_test_scenarios(self) -> list[ModelScenario[AIAgentAccess]]:
        """Check default denial, staff-only access, and authenticated access."""
        return [
            ModelScenario(
                name=name,
                preparation=self.prepare_actors,
                create_args=self.grant_args,
                create_validators=self.defaults_are_private,
                update_args=flags,
                update_validators=self.audience_matches,
            )
            for name, flags in (
                ("Both flags default to false", {}),
                ("All staff includes active staff only", {"all_staff_users": True}),
                (
                    "All authenticated includes active non-staff",
                    {"all_authenticated_users": True},
                ),
                (
                    "Audience grants may be combined",
                    {"all_staff_users": True, "all_authenticated_users": True},
                ),
            )
        ]

    def defaults_are_private(self, grant: AIAgentAccess) -> bool:
        """Ensure migrations and ORM defaults do not open any broad audience."""
        return not grant.all_staff_users and not grant.all_authenticated_users

    def audience_matches(self, grant: AIAgentAccess) -> bool:
        """Match precisely the configured audiences and always reject anonymous/inactive."""
        return (
            AIAgentAccessManager(self.member).can_use(self.agent)
            == grant.all_authenticated_users
            and AIAgentAccessManager(self.staff).can_use(self.agent)
            == (grant.all_staff_users or grant.all_authenticated_users)
            and not AIAgentAccessManager(self.inactive).can_use(self.agent)
            and not AIAgentAccessManager(AnonymousUser()).can_use(self.agent)
        )
