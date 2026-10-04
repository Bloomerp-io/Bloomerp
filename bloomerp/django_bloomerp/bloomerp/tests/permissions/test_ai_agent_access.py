"""Exercise explicit agent-use authorization at the manager and controller boundaries."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from bloomerp.agents.access import AIAgentAccessManager
from bloomerp.agents.controller import AgentController
from bloomerp.models.agents import AIAgent, AIAgentAccess
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.agents.test_controller import agent_test_config


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class AIAgentAccessTests(TestCase):
    """Cover creators, direct users, group membership, revocation, and denied actors."""

    def setUp(self) -> None:
        """Create an encrypted agent with no administrative policies assigned."""
        self.owner = get_user_model().objects.create_user(username="agent-creator")
        self.user = get_user_model().objects.create_user(username="agent-member")
        self.admin = get_user_model().objects.create_user(
            username="agent-admin", is_superuser=True
        )
        self.agent = AIAgent.objects.create(
            name="Shared assistant",
            provider="openai",
            model_identifier="example",
            created_by=self.owner,
        )
        self.agent.set_credentials({"api_key": "access-secret"})
        self.agent.save()
        self.grant = AIAgentAccess.objects.create(name="Team access", model=self.agent)

    def test_creator_is_allowed_without_view_policies(self) -> None:
        """Grant safe agent use automatically to its creator, without admin access."""
        self.assertTrue(AIAgentAccessManager(self.owner).can_use(self.agent))
        self.assertFalse(
            UserPolicyManager(self.owner).has_access_to_object(self.agent, "change")
        )
        self.assertEqual(
            AgentController(self.owner).select_agent(self.agent.pk), self.agent
        )
        self.assertEqual(
            AgentController(self.owner).available_agents(),
            [
                {"id": str(self.agent.pk), "name": self.agent.name},
            ],
        )

    def test_direct_group_and_revocation_grants_are_live(self) -> None:
        """Resolve user/group grants without duplicate picker entries or cached access."""
        manager = AIAgentAccessManager(self.user)
        self.assertFalse(manager.can_use(self.agent))
        self.grant.users.add(self.user)
        self.assertTrue(manager.can_use(self.agent))
        group = Group.objects.create(name="Agent team")
        self.user.groups.add(group)
        self.grant.groups.add(group)
        self.assertEqual(manager.get_accessible_queryset().count(), 1)
        self.grant.users.clear()
        self.assertTrue(manager.can_use(self.agent))
        self.user.groups.clear()
        self.assertFalse(manager.can_use(self.agent))
        with self.assertRaises(PermissionDenied):
            AgentController(self.user).select_agent(self.agent.pk)
        with self.assertRaises(PermissionDenied):
            AgentController(self.user).get_credentials(self.agent.runtime_config())

    def test_anonymous_inactive_and_ungranted_users_are_denied(self) -> None:
        """Deny missing/inactive identities while retaining administrator access."""
        self.assertFalse(AIAgentAccessManager(AnonymousUser()).can_use(self.agent))
        self.assertFalse(AIAgentAccessManager(self.user).can_use(self.agent))
        self.assertTrue(AIAgentAccessManager(self.admin).can_use(self.agent))
        self.owner.is_active = False
        self.owner.save()
        self.assertFalse(AIAgentAccessManager(self.owner).can_use(self.agent))

    def test_use_grant_does_not_allow_configuration_and_disabled_agents_are_hidden(
        self,
    ) -> None:
        """Keep administrative access separate and reject disabled next-run choices."""
        self.grant.users.add(self.user)
        self.assertFalse(
            UserPolicyManager(self.user).has_access_to_object(self.agent, "change")
        )
        self.assertTrue(AIAgentAccessManager(self.user).can_use(self.agent))
        self.agent.enabled = False
        self.agent.save()
        self.assertEqual(AgentController(self.user).available_agents(), [])
        with self.assertRaises(PermissionDenied):
            AgentController(self.user).select_agent(self.agent.pk)

    def test_staff_flag_and_account_revocation_refresh_stale_actors(self) -> None:
        """Drop staff and active status live even when a socket retains an old actor."""
        self.grant.all_staff_users = True
        self.grant.save()
        self.user.is_staff = True
        self.user.save()
        manager = AIAgentAccessManager(self.user)
        self.assertTrue(manager.can_use(self.agent))
        type(self.user).objects.filter(pk=self.user.pk).update(is_staff=False)
        self.assertFalse(manager.can_use(self.agent))
        self.grant.all_authenticated_users = True
        self.grant.save()
        self.assertTrue(manager.can_use(self.agent))
        type(self.user).objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertFalse(manager.can_use(self.agent))

    def test_revoked_agent_grant_blocks_tool_dispatch(self) -> None:
        """Recheck live use grants before tools, independently of the tool allowlist."""
        from bloomerp.agents.mcp import LocalMcpClient

        self.grant.all_authenticated_users = True
        self.grant.save()
        client = LocalMcpClient(self.user.pk, "https://testserver", self.agent.pk)
        client.check_tool_access(self.agent.pk, "api_assistant_mutations")
        self.grant.all_authenticated_users = False
        self.grant.save()
        with self.assertRaises(PermissionDenied):
            client.check_tool_access(self.agent.pk, "api_assistant_mutations")
        with self.assertRaises(PermissionDenied):
            client.request("tools/list")
