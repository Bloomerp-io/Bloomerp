"""Owner-scoped generated API and MCP contracts for ordinary authenticated users."""

import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from django.http import HttpResponse
from django.test import override_settings
from django.urls import reverse

from bloomerp.agents.controller import AgentController
from bloomerp.models import User
from bloomerp.models.agents import AIAgentAccess, AIConversation, AIMessage, AIRun
from bloomerp.tests.agents.test_controller import (
    agent_test_config,
    configure_test_agent,
)
from bloomerp.tests.base import (
    BloomerpAPIModelViewTestCase,
    ExpectedResult,
    RequestScenario,
)


class ConversationFixtures:
    """Build ordinary actors with agent-use access and no administrative policies."""

    def extendedSetup(self) -> None:
        """Seed both owners' transcripts and a globally authenticated use grant."""
        self.normal_user.is_staff = False
        self.normal_user.save(update_fields=["is_staff"])
        self.other = User.objects.create_user(username="other-conversation-owner")
        self.agent = configure_test_agent(self.admin_user)
        self.grant = AIAgentAccess.objects.create(
            name="All signed-in actors", model=self.agent, all_authenticated_users=True
        )
        self.own = AIConversation.objects.create(
            owner=self.normal_user, selected_agent=self.agent
        )
        self.foreign = AIConversation.objects.create(
            owner=self.other, selected_agent=self.agent
        )
        self.own_message = self.own.append_message(
            content=[{"type": "text", "text": "Own"}], role="user", message_id=uuid4()
        )
        self.foreign_message = self.foreign.append_message(
            content=[{"type": "text", "text": "Private"}],
            role="user",
            message_id=uuid4(),
        )

    def results(self, response: HttpResponse) -> list[dict[str, Any]]:
        """Accept the configured paginated or unpaginated generated response."""
        data = response.json()
        return data.get("results", []) if isinstance(data, dict) else data

    def revoke(self, scenario: RequestScenario) -> None:
        """Revoke the flag without changing the actor or an existing conversation."""
        self.grant.all_authenticated_users = False
        self.grant.save(update_fields=["all_authenticated_users"])


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class TestAIConversationAPI(ConversationFixtures, BloomerpAPIModelViewTestCase):
    """Exercise default access on the actual generated conversation collection."""

    model = AIConversation
    view_name = "ai_conversations-list"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Describe safe reads/creates and forged or anonymous requests."""
        return [
            RequestScenario(
                name="Non-staff reads only own conversations",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.only_own),
            ),
            RequestScenario(
                name="Private related fields cannot be probed by filters",
                user=self.normal_user,
                query_params={
                    "filter": json.dumps(
                        [
                            {
                                "connector": "AND",
                                "conditions": [
                                    {
                                        "field_path": "selected_agent__name",
                                        "lookup_id": "equals",
                                        "value": self.agent.name,
                                    }
                                ],
                            }
                        ]
                    )
                },
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Public title remains filterable",
                user=self.normal_user,
                query_params={"title": self.own.title},
                expected=ExpectedResult(response_validators=self.only_own),
            ),
            RequestScenario(
                name="Even administrators do not inherit private transcripts",
                user=self.admin_user,
                expected=ExpectedResult(response_validators=self.no_rows),
            ),
            RequestScenario(
                name="Anonymous cannot read", expected=ExpectedResult(status_code=401)
            ),
            RequestScenario(
                name="Non-staff creates an owned conversation",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={
                    "title": "New conversation",
                    "selected_agent": str(self.agent.pk),
                },
                expected=ExpectedResult(
                    status_code=201, response_validators=self.created_owned
                ),
            ),
            RequestScenario(
                name="Forged owner rejected",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={"owner": str(self.other.pk)},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Forged approval policy rejected",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={"approval_rules": {"mode": "none"}},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Revocation prevents a new conversation",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={"title": "Denied"},
                prepare=self.revoke,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def only_own(self, response: HttpResponse) -> bool:
        """Return exactly the actor's conversation and safe metadata."""
        rows = self.results(response)
        return [row["id"] for row in rows] == [
            str(self.own.pk)
        ] and "owner" not in rows[0]

    def no_rows(self, response: HttpResponse) -> bool:
        """Keep an administrator's own empty history private from other users."""
        return self.results(response) == []

    def created_owned(self, response: HttpResponse) -> bool:
        """Check both ownership and audit identity were assigned server-side."""
        row = AIConversation.objects.get(pk=response.json()["id"])
        return (
            row.owner_id == self.normal_user.pk
            and row.created_by_id == self.normal_user.pk
        )


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(),
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class TestAIMessageAPI(ConversationFixtures, BloomerpAPIModelViewTestCase):
    """Create user messages/runs safely and exercise real offline execution."""

    model = AIMessage
    view_name = "ai_messages-list"
    auto_create_customers = False

    def payload(self) -> dict[str, Any]:
        """Supply only user-editable fields accepted by the shared API boundary."""
        return {
            "conversation": str(self.own.pk),
            "content_blocks": [{"type": "text", "text": "Hello"}],
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Reject forged runtime fields and foreign conversations before persistence."""
        cases = [
            RequestScenario(
                name="Non-staff reads only own messages",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.only_own),
            ),
            RequestScenario(
                name="Anonymous cannot send",
                method="POST",
                content_type="application/json",
                data=self.payload(),
                expected=ExpectedResult(status_code=401),
            ),
            RequestScenario(
                name="User sends text and starts owned run",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data=self.payload(),
                expected=ExpectedResult(
                    status_code=201, response_validators=self.started_owned
                ),
            ),
            RequestScenario(
                name="Foreign conversation rejected",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={**self.payload(), "conversation": str(self.foreign.pk)},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Revoked grant prevents messages and runs",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data=self.payload(),
                prepare=self.revoke,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Forged tool content rejected",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={
                    **self.payload(),
                    "content_blocks": [
                        {"type": "approval", "approval_id": str(uuid4())}
                    ],
                },
                expected=ExpectedResult(status_code=400),
            ),
        ]
        for name, value in {
            "role": "assistant",
            "run": str(uuid4()),
            "sequence": 999,
            "status": "completed",
            "created_by": str(self.other.pk),
            "agent_id": str(self.agent.pk),
        }.items():
            cases.append(
                RequestScenario(
                    name=f"Reject forged {name}",
                    user=self.normal_user,
                    method="POST",
                    content_type="application/json",
                    data={**self.payload(), name: value},
                    expected=ExpectedResult(status_code=403),
                )
            )
        return cases

    def only_own(self, response: HttpResponse) -> bool:
        """Expose only the owner's transcript entry."""
        return [row["id"] for row in self.results(response)] == [
            str(self.own_message.pk)
        ]

    def started_owned(self, response: HttpResponse) -> bool:
        """Verify the posted text is a user message linked to a server-initiated run."""
        message = AIMessage.objects.get(pk=response.json()["id"])
        run = message.triggered_runs.get()
        return (
            message.role == "user"
            and run.initiated_by_id == self.normal_user.pk
            and run.conversation_id == self.own.pk
        )

    def test_http_submission_completes_real_offline_runtime(self) -> None:
        """Cross the real route, commit, controller and provider adapter without network."""
        self.client.force_login(self.normal_user)
        conversation_response = self.client.post(
            reverse("ai_conversations-list"),
            {"title": "API lifecycle", "selected_agent": str(self.agent.pk)},
            content_type="application/json",
        )
        self.assertEqual(
            conversation_response.status_code, 201, conversation_response.content
        )
        payload = {**self.payload(), "conversation": conversation_response.json()["id"]}
        with patch.object(AgentController, "worker_mode", return_value=False):
            response = self.client.post(
                reverse(self.view_name), payload, content_type="application/json"
            )
        self.assertEqual(response.status_code, 201, response.content)
        message = AIMessage.objects.get(pk=response.json()["id"])
        run = message.triggered_runs.get()
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.initiated_by_id, self.normal_user.pk)
        self.assertEqual(message.created_by_id, self.normal_user.pk)
        self.assertEqual(
            run.messages.get(role="assistant").content_blocks[0]["text"],
            "Hello from the agent.",
        )
        self.assertEqual(AIRun.objects.count(), 1)

    def test_nested_projection_does_not_expand_message_content(self) -> None:
        """Keep configured nested field selections narrower than the safe full transcript."""
        from django.test import RequestFactory

        from bloomerp.utils.api import generate_serializer

        request = RequestFactory().get("/")
        request.user = self.normal_user
        serializer = generate_serializer(AIMessage)(
            self.own_message,
            context={
                "request": request,
                "bloomerp_nested_fields": {"role"},
                "bloomerp_auto_pk": False,
            },
        )
        self.assertEqual(serializer.data, {"role": "user"})

    def test_administrators_cannot_forge_or_rewrite_private_records(self) -> None:
        """Keep the transcript contract even when generic policy checks allow all fields."""
        self.client.force_login(self.admin_user)
        owned = AIConversation.objects.create(
            owner=self.admin_user, selected_agent=self.agent
        )
        message = owned.append_message(
            content=[{"type": "text", "text": "Original"}],
            role="user",
            message_id=uuid4(),
        )
        for field, value in {
            "role": "assistant",
            "status": "streaming",
            "run": str(uuid4()),
            "sequence": 99,
        }.items():
            response = self.client.post(
                reverse("ai_messages-list"),
                {
                    **self.payload(),
                    "conversation": str(owned.pk),
                    field: value,
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(
            reverse("ai_conversations-list"),
            {"owner": str(self.other.pk)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        for name, row in (
            ("ai_conversations-detail", owned),
            ("ai_messages-detail", message),
        ):
            for method in (self.client.patch, self.client.delete):
                response = method(
                    reverse(name, kwargs={"pk": row.pk}),
                    {},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 404, response.content)
        self.assertTrue(AIMessage.objects.filter(pk=message.pk).exists())

    def test_catalog_advertises_only_safe_creates(self) -> None:
        """Even administrators see the private API's actual immutable contract."""
        self.client.force_login(self.admin_user)
        for model in (AIConversation, AIMessage):
            response = self.client.get(
                reverse("api_assistant_mutation_catalog"),
                {"model_label": model._meta.label},
            )
            self.assertEqual(response.status_code, 200, response.content)
            resource = response.json()["resources"][0]
            self.assertEqual(set(resource["operations"]), {"create"})
            fields = {
                field["name"] for field in resource["operations"]["create"]["fields"]
            }
            self.assertTrue(
                fields.isdisjoint(
                    {
                        "owner",
                        "role",
                        "run",
                        "status",
                        "sequence",
                        "created_by",
                        "approval_rules",
                    }
                )
            )

    def test_inactive_actor_cannot_read_or_send(self) -> None:
        """Recheck activity even when a transport supplies a previously loaded identity."""
        from rest_framework.test import APIRequestFactory, force_authenticate

        from bloomerp.views.api.generic.list import BloomerpListApiView

        User.objects.filter(pk=self.normal_user.pk).update(is_active=False)
        factory = APIRequestFactory()
        for method, action in ((factory.get, "list"), (factory.post, "create")):
            request = method(
                "/api/ai_messages/",
                self.payload() if action == "create" else {},
                format="json",
            )
            force_authenticate(request, user=self.normal_user)
            response = BloomerpListApiView.as_view(
                {"get": "list", "post": "create"}, model=AIMessage
            )(request)
            if action == "list":
                self.assertEqual(response.data, [])
            else:
                self.assertEqual(response.status_code, 403)

    def test_detail_and_mutations_never_cross_owners(self) -> None:
        """Ensure detail, destructive and MCP-adapter paths retain the same boundary."""
        self.client.force_login(self.normal_user)
        for model, foreign in (
            (AIConversation, self.foreign),
            (AIMessage, self.foreign_message),
        ):
            name = (
                "ai_conversations-detail"
                if model is AIConversation
                else "ai_messages-detail"
            )
            for method in (self.client.get, self.client.patch, self.client.delete):
                response = method(
                    reverse(name, kwargs={"pk": foreign.pk}),
                    {},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 404, response.content)
            response = self.client.post(
                reverse("api_assistant_mutations"),
                {
                    "model_label": model._meta.label,
                    "operation": "delete",
                    "object_id": str(foreign.pk),
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 404, response.content)
