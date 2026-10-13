"""Exercise protected model selection and durable configuration at the controller boundary."""

import asyncio
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from bloomerp.agents.controller import (
    AgentChatRequest,
    AgentController,
    AgentConversationEdit,
)
from bloomerp.models.agents import AIAgent, AIRun
from bloomerp.tests.agents.test_controller import (
    agent_test_config,
    configure_test_agent,
    interrupted_runtime,
)


@override_settings(
    BLOOMERP_CONFIG=agent_test_config(),
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class AIAgentSelectionTests(TestCase):
    """Cover the real authorization, encrypted storage, and pinned execution boundaries."""

    def setUp(self) -> None:
        """Create one permitted actor, one denied actor, and an offline configured model."""
        self.user = get_user_model().objects.create_user(username="model-owner")
        self.other = get_user_model().objects.create_user(username="model-denied")
        self.model = configure_test_agent(self.user)
        self.controller = AgentController(self.user)

    def request(
        self, model: AIAgent | None = None, conversation_id: UUID | None = None
    ) -> AgentChatRequest:
        """Build a unique plain-text submission with an optional next-run choice."""
        return AgentChatRequest(
            content=[{"type": "text", "text": "Hello"}],
            client_message_id=uuid4(),
            agent_id=model.pk if model else None,
            conversation_id=conversation_id,
        )

    def execute(self, run: AIRun) -> None:
        """Consume an offline attempt and reload the committed run state."""
        async_to_sync(self.controller.run_attempt)(
            run.pk, execution_mode="inline", executor_id="test"
        )
        run.refresh_from_db()

    def test_credentials_are_encrypted_and_excluded_from_snapshots_and_picker(
        self,
    ) -> None:
        """Allow model use without publishing the stored or resolved secret values."""
        submission = self.controller.accept_message(self.request(self.model))
        run = AIRun.objects.get(pk=submission.run_id)
        self.assertNotIn(
            "never-store-this-secret", str(self.model.credentials_encrypted)
        )
        self.assertNotIn("never-store-this-secret", str(run.config_snapshot))
        self.assertNotIn("credentials", str(self.controller.available_agents()))
        credentials = self.controller.get_credentials(run.runtime_config())
        self.assertNotIn("never-store-this-secret", credentials.model_dump_json())
        self.assertNotIn("never-store-this-secret", repr(credentials))
        self.assertEqual(
            credentials.api_key.get_secret_value(), "never-store-this-secret"
        )
        self.assertFalse(self.model.bloomerp_config.api_settings.enable_auto_generation)
        self.assertFalse(self.model._meta.get_field("credentials_encrypted").editable)
        self.assertEqual(
            set(self.model.credentials_encrypted),
            {"version", "algorithm", "ciphertext"},
        )
        self.model.refresh_from_db()
        self.assertEqual(self.model.credentials_encrypted["algorithm"], "fernet")
        self.assertNotIn("capabilities", run.config_snapshot)

    def test_disabled_revoked_and_unknown_models_are_denied(self) -> None:
        """Filter the picker and reject unavailable identities at run acceptance."""
        denied = AgentController(self.other)
        self.assertEqual(denied.available_agents(), [])
        with self.assertRaises(PermissionDenied):
            denied.accept_message(self.request(self.model))
        with self.assertRaises(PermissionDenied):
            self.controller.accept_message(
                self.request().model_copy(update={"agent_id": uuid4()})
            )
        self.model.enabled = False
        self.model.save()
        self.assertEqual(self.controller.available_agents(), [])
        with self.assertRaises(PermissionDenied):
            self.controller.accept_message(self.request(self.model))

    def test_conversation_switch_only_changes_future_runs(self) -> None:
        """Persist the next-run choice while leaving the active run's snapshot immutable."""
        first = AIRun.objects.get(
            pk=self.controller.accept_message(self.request(self.model)).run_id
        )
        second = AIAgent.objects.create(
            name="Second model",
            created_by=self.user,
            provider=self.model.provider,
            model_identifier="another-model",
            default_instructions="Second instructions",
            max_tokens=500,
        )
        second.set_credentials({"api_key": "second-secret"})
        second.save()
        self.controller.edit_conversation(
            AgentConversationEdit(
                request_id=uuid4(),
                conversation_id=first.conversation_id,
                agent_id=second.pk,
            )
        )
        first.refresh_from_db()
        self.assertEqual(first.runtime_config().model, "offline")
        self.assertEqual(first.budgets["max_tokens"], 20000)
        self.execute(first)
        self.assertEqual(first.status, "completed", first.error)
        next_run = AIRun.objects.get(
            pk=self.controller.accept_message(
                self.request(conversation_id=first.conversation_id)
            ).run_id
        )
        self.assertEqual(next_run.runtime_config().model, "another-model")
        self.assertEqual(next_run.budgets["max_tokens"], 500)
        self.assertEqual(
            next_run.config_snapshot["instructions"], "Second instructions"
        )

    def test_resume_uses_snapshot_after_edits_and_rotates_credentials(self) -> None:
        """Keep the provider, model, endpoint, and budgets pinned across interrupted attempts."""
        run = AIRun.objects.get(
            pk=self.controller.accept_message(self.request(self.model)).run_id
        )
        pinned = run.runtime_config()
        with (
            patch.object(
                self.controller, "get_runtime", return_value=interrupted_runtime(pinned)
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            self.execute(run)
        run.refresh_from_db()
        self.assertTrue(run.checkpoint)
        self.model.provider = "anthropic"
        self.model.model_identifier = "edited-model"
        self.model.base_url = "https://edited.example.test"
        self.model.default_instructions = "Changed instructions"
        self.model.max_tokens = 1
        self.model.enabled = False
        self.model.set_credentials({"api_key": "rotated-secret"})
        self.model.save()
        attempt = run.attempts.get()
        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save()
        self.assertEqual(run.runtime_config(), pinned)
        self.assertEqual(
            self.controller.get_credentials(pinned).api_key.get_secret_value(),
            "rotated-secret",
        )
        self.execute(run)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.runtime_config(), pinned)
        self.assertEqual(run.budgets["max_tokens"], 20000)

    def test_provider_parameters_and_positive_run_budgets_are_validated(self) -> None:
        """Reject unsupported provider options and distinguish run totals from response caps."""
        self.model.parameters = {"extra_headers": {"Authorization": "secret"}}
        with self.assertRaises(ValidationError):
            self.model.save()
        self.model.parameters = {"max_tokens": 100}
        self.model.max_tokens = 900
        self.model.save()
        self.assertEqual(self.model.runtime_config().parameters["max_tokens"], 100)
        self.assertEqual(self.model.run_budgets().max_tokens, 900)
        self.model.max_tool_calls = 0
        with self.assertRaises(ValidationError):
            self.model.save()

    def test_creator_and_group_use_grants_are_independent_of_view_policies(
        self,
    ) -> None:
        """Use explicit agent grants while keeping administrative policies separate."""
        from django.contrib.auth.models import Group

        from bloomerp.models.agents import AIAgentAccess

        extra = AIAgent.objects.create(
            name="Hidden model", provider=self.model.provider, model_identifier="hidden"
        )
        extra.set_credentials({"api_key": "hidden-secret"})
        extra.save()
        self.assertEqual(
            self.controller.available_agents(),
            [{"id": str(self.model.pk), "name": self.model.name}],
        )
        with self.assertRaises(PermissionDenied):
            self.controller.accept_message(self.request(extra))
        group = Group.objects.create(name="Agent users")
        group.user_set.add(self.other)
        grant = AIAgentAccess.objects.create(name="Team access", model=self.model)
        grant.groups.add(group)
        self.assertEqual(
            AgentController(self.other).available_agents(),
            self.controller.available_agents(),
        )
        self.user.access_control_policies.clear()
        self.assertEqual(self.controller.available_agents()[0]["name"], self.model.name)
        grant.groups.clear()
        self.assertEqual(AgentController(self.other).available_agents(), [])

    def test_credential_envelope_validation_and_empty_model_selection(self) -> None:
        """Reject malformed storage and keep models without configured credentials out of the picker."""
        self.model.credentials_encrypted = {
            "version": 2,
            "algorithm": "plaintext",
            "ciphertext": "invalid",
        }
        with self.assertRaises(ValidationError):
            self.model.save()
        with self.assertRaises(ValidationError):
            self.model.validated_credentials()
        self.model.credentials_encrypted = {}
        self.model.save()
        self.assertEqual(self.controller.available_agents(), [])
        with self.assertRaises(PermissionDenied):
            self.controller.accept_message(self.request(self.model))

    def test_ai_agent_fields_have_translated_labels_and_help(self) -> None:
        """Give each model-owned configuration field meaningful lazy-translated metadata."""
        from django.db import models
        from django.utils.functional import Promise

        for field in AIAgent._meta.local_fields:
            if field.name in {
                "avatar",
                "id",
                "datetime_created",
                "datetime_updated",
                "created_by",
                "updated_by",
            }:
                continue
            self.assertIsInstance(field.verbose_name, Promise, field.name)
            self.assertIsInstance(field.help_text, Promise, field.name)
            self.assertTrue(str(field.help_text), field.name)
        self.assertIsInstance(
            AIAgent._meta.get_field("credentials_encrypted"), models.JSONField
        )
        self.assertNotIn("capabilities", [field.name for field in AIAgent._meta.fields])
