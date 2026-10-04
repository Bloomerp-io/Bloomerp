"""Declarative lifecycle coverage for account-independent MCP integrations."""

from typing import Any

from django.core.exceptions import ValidationError

from bloomerp.models.agents import MCPConnection, MCPIntegration
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)


class TestMCPIntegrationModel(BloomerpModelTestCase):
    """Exercise safe endpoint configuration and changes with existing accounts."""

    model = MCPIntegration

    def integration_args(self) -> dict[str, Any]:
        """Describe a shared integration with API-key authentication."""
        return {
            "name": "External tools",
            "endpoint_url": "https://example.com/mcp",
            "authentication_type": "api_key",
        }

    def add_connection(self, integration: MCPIntegration) -> None:
        """Create a pending shared account before configuration changes."""
        MCPConnection.objects.create(integration=integration)

    def get_test_scenarios(self) -> list[ModelScenario[MCPIntegration]]:
        """Declare valid metadata and rejected credential-breaking changes."""
        scenarios = [
            ModelScenario(
                name="No-auth integration needs no connection",
                create_args={
                    "name": "Public tools",
                    "endpoint_url": "https://example.com/mcp",
                },
                create_validators=self.no_connection,
            ),
            ModelScenario(
                name="Mode can change without existing connections",
                create_args=self.integration_args,
                update_args={"connection_mode": "personal"},
                update_validators=self.personal_mode,
            ),
            ModelScenario(
                name="Enabled state can change with existing connections",
                create_args=self.integration_args,
                post_create=self.add_connection,
                update_args={"enabled": False},
                update_validators=self.disabled,
            ),
        ]
        for field, value in (
            ("connection_mode", "personal"),
            ("authentication_type", "oauth"),
            ("endpoint_url", "https://other.example.com/mcp"),
        ):
            scenarios.append(
                ModelScenario(
                    name=f"Existing connection blocks {field} change",
                    create_args=self.integration_args,
                    post_create=self.add_connection,
                    update_args={field: value},
                    expected_exceptions=[
                        ExpectedModelException(
                            "update", ValidationError, "Remove existing"
                        )
                    ],
                )
            )
        for url in (
            "https://name:secret@example.com/mcp",
            "https://example.com/mcp?token=secret",
            "https://example.com/mcp#secret",
            "ftp://example.com/mcp",
        ):
            scenarios.append(
                ModelScenario(
                    name=f"Unsafe endpoint rejected: {url}",
                    create_args={**self.integration_args(), "endpoint_url": url},
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                )
            )
        return scenarios

    def no_connection(self, integration: MCPIntegration) -> bool:
        """Verify public metadata persists without an account record."""
        return (
            not integration.connections.exists() and str(integration) == "Public tools"
        )

    def personal_mode(self, integration: MCPIntegration) -> bool:
        """Verify a configuration change persists while there are no accounts."""
        return integration.connection_mode == "personal"

    def disabled(self, integration: MCPIntegration) -> bool:
        """Verify disabling preserves an existing pending account."""
        return not integration.enabled and integration.connections.count() == 1
