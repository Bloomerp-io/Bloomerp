"""Workspace authoring resource discovery, live schemas and access enforcement."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from jsonschema import Draft202012Validator
from pydantic import Field

from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.definition import FieldLayout
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpMcpViewTestCase, ExpectedResult, McpRequestScenario
from bloomerp.views.mcp.workspaces_resource import workspace_resource
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.base import BaseTileConfig, TileTypeDefinition
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY
from bloomerp.workspaces.text_tile.render import TextTileRenderer


def forbidden_default() -> str:
    """Fail if a reference read tries to construct a configuration default."""
    raise AssertionError("Resource reads must not evaluate configuration defaults")


class ExtensionConfig(BaseTileConfig):
    """Supply an extension schema with a runtime default that must not be evaluated."""

    markdown: str = Field(default_factory=forbidden_default, description="Extension content.")


class WorkspaceResourceMetadataTests(SimpleTestCase):
    """Inspect schema exports without saved records or tile execution."""

    def read_resource(self) -> dict[str, Any]:
        """Read the reference with only its permission check mocked."""
        request = HttpRequest()
        request.user = SimpleNamespace(is_authenticated=True)
        with patch("bloomerp.views.mcp.workspaces_resource.UserPolicyManager") as manager:
            manager.return_value.has_global_permission.return_value = True
            return workspace_resource(request)

    def test_installed_schemas_and_guide_are_current(self) -> None:
        """Use case: An authorized agent reads construction guidance.
        Expected result: The reference exports current schemas and mutation instructions.
        """
        # 1. Read and validate every exported schema.
        document = self.read_resource()
        self.assertEqual(document["layout_schema"], FieldLayout.model_json_schema())
        Draft202012Validator.check_schema(document["layout_schema"])
        tiles = {item["type"]: item for item in document["tile_types"]}
        self.assertEqual(set(tiles), {key for key, _ in TILE_TYPE_REGISTRY.items()})
        for key, definition in TILE_TYPE_REGISTRY.items():
            self.assertEqual(tiles[key]["description"], definition.description)
            self.assertEqual(tiles[key]["config_schema"], definition.model.model_json_schema())
            Draft202012Validator.check_schema(tiles[key]["config_schema"])
        # 2. Check analytics branches, hidden link fields, and guide layout references.
        self.assertEqual(tiles["ANALYTICS_TILE"]["config_schema"], AnalyticsTileConfig.model_json_schema())
        self.assertIn("oneOf", tiles["ANALYTICS_TILE"]["config_schema"])
        links = tiles["LINKS_TILE"]["config_schema"]
        self.assertNotIn("id", links["properties"])
        self.assertNotIn("url_name", links["$defs"]["Link"]["properties"])
        self.assertNotIn("is_internal", links["$defs"]["Link"]["properties"])
        guide = document["guide"]
        example = json.loads(guide.split("```json\n", 1)[1].split("```", 1)[0])
        Draft202012Validator(document["layout_schema"]).validate(example)
        self.assertIn("api_assistant_mutation_catalog", guide)
        self.assertIn("api_assistant_mutations", guide)
        self.assertIn("get_content_type", guide)
        self.assertEqual(document["models"], {"workspace": "bloomerp.Workspace", "tile": "bloomerp.Tile"})

    def test_next_read_includes_extension_without_constructing_it(self) -> None:
        """Use case: A tile extension is registered after an earlier reference read.
        Expected result: The next read includes its schema without evaluating defaults.
        """
        # 1. Read once, then register a new extension and a metadata-only type.
        before = self.read_resource()
        TILE_TYPE_REGISTRY.register("REFERENCE_EXTENSION", TileTypeDefinition(
            name="Extension", description="Installed extension tile.",
            model=ExtensionConfig, render_cls=TextTileRenderer,
        ))
        self.addCleanup(TILE_TYPE_REGISTRY.unregister, "REFERENCE_EXTENSION")
        TILE_TYPE_REGISTRY.register("REFERENCE_METADATA", TileTypeDefinition(
            name="Metadata", description="No configuration model.",
        ))
        self.addCleanup(TILE_TYPE_REGISTRY.unregister, "REFERENCE_METADATA")
        # 2. Check both new types and the extension's field description.
        after = self.read_resource()
        self.assertEqual(len(after["tile_types"]), len(before["tile_types"]) + 2)
        tiles = {item["type"]: item for item in after["tile_types"]}
        self.assertEqual(tiles["REFERENCE_EXTENSION"]["config_schema"]["properties"]["markdown"]["description"], "Extension content.")
        self.assertTrue(tiles["REFERENCE_EXTENSION"]["renderable"])
        self.assertIsNone(tiles["REFERENCE_METADATA"]["config_schema"])
        self.assertFalse(tiles["REFERENCE_METADATA"]["renderable"])

    def test_direct_anonymous_read_is_denied(self) -> None:
        """Use case: The resource function is called without MCP authentication.
        Expected result: Anonymous callers cannot read the reference directly.
        """
        # 1. Construct a request with an anonymous actor.
        request = HttpRequest()
        request.user = AnonymousUser()
        # 2. Require the reader itself to reject access.
        with self.assertRaises(PermissionDenied):
            workspace_resource(request)


class TestWorkspacesResourceView(BloomerpMcpViewTestCase):
    """Exercise the real MCP resource transport with declarative permission scenarios."""

    view_name = "workspace_resource"

    def workspace_document_is_live(self, response: HttpResponse) -> bool:
        """Check the JSON resource envelope and its current registered tile types."""
        contents = response.json().get("result", {}).get("contents", [])
        if len(contents) != 1:
            return False
        document = json.loads(contents[0]["text"])
        return (
            contents[0]["uri"] == "bloomerp://guides/create-workspace"
            and contents[0]["mimeType"] == "application/json"
            and {item["type"] for item in document["tile_types"]}
            == {key for key, _ in TILE_TYPE_REGISTRY.items()}
        )

    def view_permission(self) -> Permission:
        """Resolve the workspace view permission used by each grant scenario."""
        return Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Workspace), codename="view_workspace",
        )

    def grant_user_permission(self, scenario: McpRequestScenario) -> None:
        """Grant workspace read access directly to the ordinary scenario actor."""
        scenario.user.user_permissions.add(self.view_permission())

    def grant_group_permission(self, scenario: McpRequestScenario) -> None:
        """Grant workspace read access through a Django group."""
        group = Group.objects.create(name="Workspace reference readers")
        group.permissions.add(self.view_permission())
        scenario.user.groups.add(group)

    def grant_policy_permission(self, scenario: McpRequestScenario) -> None:
        """Grant workspace read access through an assigned policy's global permissions."""
        content_type = ContentType.objects.get_for_model(Workspace)
        policy = Policy.objects.create(
            name="Workspace reference policy",
            row_policy=RowPolicy.objects.create(content_type=content_type),
            field_policy=FieldPolicy.objects.create(
                name="Workspace reference fields", content_type=content_type, rule={},
            ),
        )
        policy.global_permissions.add(self.view_permission())
        policy.users.add(scenario.user)

    def get_test_scenarios(self) -> list[McpRequestScenario]:
        """Cover superuser, no-grant, anonymous and supported permission grant paths."""
        scenarios = [
            McpRequestScenario(
                name="Superuser reads live workspace authoring metadata", user=self.admin_user,
                expected=ExpectedResult(response_validators=self.workspace_document_is_live),
            ),
            McpRequestScenario(
                name="Ordinary user without workspace view permission is denied", user=self.normal_user,
                expected=ExpectedResult(response_validators=self.mcp_rpc_error(-32001)),
            ),
            McpRequestScenario(
                name="Anonymous resource read requires authentication",
                expected=ExpectedResult(status_code=401),
            ),
        ]
        for name, prepare in (
            ("Direct Django permission", self.grant_user_permission),
            ("Group Django permission", self.grant_group_permission),
            ("Policy global permission", self.grant_policy_permission),
        ):
            scenarios.append(McpRequestScenario(
                name=f"{name} grants workspace reference access", user=self.normal_user, prepare=prepare,
                expected=ExpectedResult(response_validators=self.workspace_document_is_live),
            ))
        return scenarios
