"""Declarative lifecycle and storage boundary checks for MCP credentials."""

import json
from collections.abc import Callable
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.forms import modelform_factory
from django.test import override_settings

from bloomerp.models.agents import MCPConnection, MCPIntegration
from bloomerp.models.agents.mcp_connection import APIKeyCredentials, OAuthCredentials
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)


class TestMCPConnectionModel(BloomerpModelTestCase):
    """Verify account uniqueness, validation, encryption and private surfaces."""

    model = MCPConnection

    def prepare_records(self) -> None:
        """Create shared, personal, public and OAuth configurations and two users."""
        common = {"name": "Tools", "endpoint_url": "https://example.com/mcp"}
        self.shared = MCPIntegration.objects.create(
            **common, authentication_type="api_key"
        )
        self.personal = MCPIntegration.objects.create(
            **common, authentication_type="api_key", connection_mode="personal"
        )
        self.public = MCPIntegration.objects.create(**common)
        self.oauth = MCPIntegration.objects.create(
            **common, authentication_type="oauth"
        )
        self.user = get_user_model().objects.create_user(username="mcp-owner")
        self.other = get_user_model().objects.create_user(username="mcp-other")

    def shared_args(self) -> dict[str, Any]:
        """Describe a pending shared account without credentials."""
        return {"integration": self.shared}

    def personal_args(self) -> dict[str, Any]:
        """Describe a personal account for the acting user."""
        return {"integration": self.personal, "user": self.user}

    def duplicate_shared_args(self) -> dict[str, Any]:
        """Attempt a second shared account for the same integration."""
        MCPConnection.objects.create(**self.shared_args())
        return self.shared_args()

    def duplicate_personal_args(self) -> dict[str, Any]:
        """Attempt a second account for the same integration and user."""
        MCPConnection.objects.create(**self.personal_args())
        return self.personal_args()

    def other_personal_args(self) -> dict[str, Any]:
        """Create distinct accounts for two users on one personal integration."""
        MCPConnection.objects.create(**self.personal_args())
        return {"integration": self.personal, "user": self.other}

    def encrypted_connection(self) -> MCPConnection:
        """Persist a ready API-key account after explicit credential encryption."""
        connection = MCPConnection(integration=self.shared, status="ready")
        connection.set_credentials({"api_key": "mcp-test-secret"})
        connection.save()
        return connection

    def oauth_connection(self) -> MCPConnection:
        """Persist an encrypted OAuth account without implementing a token flow."""
        connection = MCPConnection(integration=self.oauth, status="ready")
        connection.set_credentials(
            {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "client_secret": "client-secret",
            }
        )
        connection.save()
        return connection

    def stale_configuration_connection(self) -> MCPConnection:
        """Attempt a connection using a cached integration whose mode has changed."""
        current = MCPIntegration.objects.get(pk=self.shared.pk)
        current.connection_mode = "personal"
        current.save()
        return MCPConnection.objects.create(integration=self.shared)

    def invalid_credentials_connection(self) -> MCPConnection:
        """Reject credentials for the wrong authentication schema."""
        connection = MCPConnection(integration=self.shared)
        connection.set_credentials({"access_token": "do-not-echo"})
        return connection

    def get_test_scenarios(self) -> list[ModelScenario[MCPConnection]]:
        """Declare account lifecycles, encrypted storage and invalid ownership."""
        scenarios = [
            ModelScenario(
                name="Encrypted API key persists privately",
                create_operation=self.encrypted_connection,
                create_validators=self.private_encrypted,
                update_args={"status": "expired"},
                update_validators=self.private_encrypted,
                delete_validators=self.deleted,
            ),
            ModelScenario(
                name="OAuth tokens persist masked",
                create_operation=self.oauth_connection,
                create_validators=self.oauth_masked,
            ),
            ModelScenario(
                name="Different users can have personal accounts",
                create_args=self.other_personal_args,
            ),
            ModelScenario(
                name="Duplicate shared rejected",
                create_args=self.duplicate_shared_args,
                expected_exceptions=[ExpectedModelException("create", ValidationError)],
            ),
            ModelScenario(
                name="Duplicate personal rejected",
                create_args=self.duplicate_personal_args,
                expected_exceptions=[ExpectedModelException("create", ValidationError)],
            ),
            ModelScenario(
                name="Stale integration cannot bypass mode validation",
                create_operation=self.stale_configuration_connection,
                expected_exceptions=[ExpectedModelException("create", ValidationError)],
            ),
            ModelScenario(
                name="Wrong credentials rejected",
                create_operation=self.invalid_credentials_connection,
                expected_exceptions=[
                    ExpectedModelException(
                        "create", ValidationError, "Invalid MCP credentials"
                    )
                ],
            ),
            ModelScenario(
                name="Ownership cannot be reassigned",
                create_args=self.personal_args,
                update_args=self.other_owner_args,
                expected_exceptions=[
                    ExpectedModelException("update", ValidationError, "immutable")
                ],
            ),
            ModelScenario(
                name="Integration cannot be reassigned",
                create_args=self.shared_args,
                update_args=self.other_integration_args,
                expected_exceptions=[
                    ExpectedModelException("update", ValidationError, "immutable")
                ],
            ),
        ]
        for name, values in (
            ("Shared account forbids user", {"integration": "shared", "user": True}),
            ("Personal account requires user", {"integration": "personal"}),
            ("No-auth account rejected", {"integration": "public"}),
            (
                "Ready requires credentials",
                {"integration": "shared", "status": "ready"},
            ),
            (
                "Plaintext storage rejected",
                {
                    "integration": "shared",
                    "credentials_encrypted": {"api_key": "mcp-test-secret"},
                },
            ),
            (
                "Malformed ciphertext rejected",
                {
                    "integration": "shared",
                    "credentials_encrypted": {
                        "version": 1,
                        "algorithm": "fernet",
                        "ciphertext": "bad",
                    },
                },
            ),
        ):
            scenarios.append(
                ModelScenario(
                    name=name,
                    create_args=self.invalid_args(values),
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                )
            )
        for scenario in scenarios:
            scenario.preparation = self.prepare_records
        return scenarios

    def invalid_args(self, values: dict[str, Any]) -> Callable[[], dict[str, Any]]:
        """Return a documented argument factory that resolves scenario fixtures later."""

        def resolve() -> dict[str, Any]:
            """Resolve the requested integration and optional user for one scenario."""
            args = values.copy()
            args["integration"] = getattr(self, args["integration"])
            if args.get("user"):
                args["user"] = self.user
            return args

        return resolve

    def other_owner_args(self) -> dict[str, Any]:
        """Describe a prohibited credential ownership transfer."""
        return {"user": self.other}

    def other_integration_args(self) -> dict[str, Any]:
        """Describe a prohibited credential transfer to another endpoint."""
        other = MCPIntegration.objects.create(
            name="Other",
            endpoint_url="https://other.example.com/mcp",
            authentication_type="api_key",
        )
        return {"integration": other}

    def private_encrypted(self, connection: MCPConnection) -> bool:
        """Verify database, forms, generated API, audit and display boundaries."""
        from bloomerp.views.api.generic.base import get_auto_api_models

        payload = MCPConnection.objects.values_list(
            "credentials_encrypted", flat=True
        ).get(pk=connection.pk)
        credentials = connection.validated_credentials()
        self.assertIsInstance(credentials, APIKeyCredentials)
        self.assertEqual(credentials.api_key.get_secret_value(), "mcp-test-secret")
        self.assertNotIn("mcp-test-secret", json.dumps(payload))
        self.assertNotIn("mcp-test-secret", str(connection))
        self.assertNotIn("mcp-test-secret", repr(credentials))
        self.assertNotIn("mcp-test-secret", credentials.model_dump_json())
        self.assertNotIn(
            "credentials_encrypted",
            modelform_factory(MCPConnection, fields="__all__").base_fields,
        )
        self.assertNotIn(MCPConnection, get_auto_api_models())
        self.assertFalse(connection.bloomerp_config.activity_log_settings.enabled)
        self.assertTrue(connection.bloomerp_config.is_internal)
        return True

    def oauth_masked(self, connection: MCPConnection) -> bool:
        """Verify all OAuth secrets round-trip and remain masked in serialization."""
        credentials = connection.validated_credentials()
        self.assertIsInstance(credentials, OAuthCredentials)
        self.assertEqual(credentials.access_token.get_secret_value(), "access-secret")
        self.assertEqual(credentials.refresh_token.get_secret_value(), "refresh-secret")
        self.assertEqual(credentials.client_secret.get_secret_value(), "client-secret")
        for secret in ("access-secret", "refresh-secret", "client-secret"):
            self.assertNotIn(secret, credentials.model_dump_json())
            self.assertNotIn(secret, json.dumps(connection.credentials_encrypted))
        return True

    def deleted(self, connection: MCPConnection) -> bool:
        """Verify deleting a connection removes its encrypted storage."""
        return not MCPConnection.objects.filter(pk=connection.pk).exists()

    def test_database_uniqueness_constraints(self) -> None:
        """Verify the database rejects duplicates even when model saves are bypassed."""
        self.prepare_records()
        for values in (self.shared_args(), self.personal_args()):
            MCPConnection.objects.create(**values)
            with self.assertRaises(IntegrityError), transaction.atomic():
                models.Model.save(MCPConnection(**values), force_insert=True)

    def test_wrong_key_and_invalid_schema_errors_hide_secrets(self) -> None:
        """Verify corrupt encryption and schema failures produce sanitized errors."""
        self.prepare_records()
        connection = self.encrypted_connection()
        with (
            override_settings(SECRET_KEY="different-instance-key"),
            self.assertRaisesRegex(ValidationError, "could not be decrypted"),
        ):
            connection.validated_credentials()
        with self.assertRaises(ValidationError) as captured:
            connection.set_credentials({"api_key": {"secret": "do-not-echo"}})
        self.assertNotIn("do-not-echo", str(captured.exception))

    def test_bulk_writes_cannot_bypass_validation(self) -> None:
        """Verify ordinary queryset bulk writes cannot bypass ownership validation."""
        self.prepare_records()
        connection = MCPConnection.objects.create(**self.shared_args())
        with self.assertRaises(TypeError):
            MCPConnection.objects.filter(pk=connection.pk).update(user=self.user)
        with self.assertRaises(TypeError):
            MCPConnection.objects.bulk_create([MCPConnection(**self.shared_args())])
        with self.assertRaises(TypeError):
            MCPIntegration.objects.filter(pk=self.shared.pk).update(
                connection_mode="personal"
            )
