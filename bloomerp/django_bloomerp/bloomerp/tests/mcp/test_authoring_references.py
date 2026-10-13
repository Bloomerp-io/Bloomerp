"""Discovery, authorization and live metadata contracts for authoring resources."""

import json
from typing import Any
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY, WorkflowNodeDefinition
from bloomerp.config.definition import (
    BloomerpAuthSettings,
    BloomerpConfig,
    OAuthSettings,
)
from bloomerp.mcp.view import McpEndpointView
from bloomerp.models.automation.workflow import Workflow
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.router import router
from bloomerp.serializers.access_control import PolicySerializer
from bloomerp.serializers.workflow import WorkflowSerializer
from bloomerp.tests.base.request_test_case_mixin import (
    ExpectedResult,
    RequestScenario,
    RequestTestCaseMixin,
)
from bloomerp.views.auth.oauth import protected_resource_metadata
from bloomerp.views.mcp.authoring_references import (
    field_reference,
    policy_reference,
    workflow_reference,
)

urlpatterns = [
    path("mcp/", McpEndpointView.as_view(), name="authoring_reference_mcp"),
    path(
        ".well-known/oauth-protected-resource",
        protected_resource_metadata,
        name="oauth_resource_metadata",
    ),
]


def forbidden_default() -> str:
    """Fail if documentation evaluates a callable default or choice provider."""
    raise AssertionError("Documentation must not evaluate dynamic providers")


class ExtensionForm(forms.Form):
    """Prove custom forms are inspected without running their constructors."""

    count = forms.IntegerField(initial=3, min_value=1, help_text="Number of items")
    mode = forms.ChoiceField(choices=[("one", "One"), ("two", "Two")], required=False)
    dynamic = forms.CharField(initial=forbidden_default)
    secret = forms.CharField(initial="must-never-leak", widget=forms.PasswordInput)
    recipient = forms.ModelChoiceField(queryset=get_user_model().objects.all())
    lazy_choice = forms.ChoiceField(choices=forbidden_default)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Reject form construction during reference generation."""
        raise AssertionError("Documentation must not instantiate forms")


class ExtensionExecutor(BaseExecutor):
    """Expose extension declarations while forbidding node construction/execution."""

    config_form = ExtensionForm
    output_ports = (WorkflowNodeOutputPort("custom", "Custom output", 2),)

    def __init__(self, parameters: dict[str, Any]) -> None:
        """Reject node construction during documentation reads."""
        raise AssertionError("Documentation must not instantiate nodes")

    def execute(self, trigger_data: dict[str, Any]) -> dict[str, Any]:
        """Reject accidental execution during documentation reads."""
        raise AssertionError("Documentation must not execute nodes")


class AuthoringReferenceMetadataTests(SimpleTestCase):
    """Verify reference reads need no database or runtime node operations."""

    def setUp(self) -> None:
        """Prepare an authenticated request without constructing database fixtures."""
        self.request = HttpRequest()
        self.request.user = get_user_model()(username="reader")

    def test_installed_app_discovery_registers_both_resources(self) -> None:
        """Find the actual automatically discovered providers outside the tool catalog."""
        resources = {route.mcp.uri: route for route in router.get_mcp_resources()}
        self.assertIs(
            resources["bloomerp://guides/create-workflow"].view, workflow_reference
        )
        self.assertIs(
            resources["bloomerp://guides/create-policy"].view, policy_reference
        )
        tool_views = {route.view for route in router.get_mcp_routes()}
        self.assertNotIn(workflow_reference, tool_views)
        self.assertNotIn(policy_reference, tool_views)

    def test_new_registered_node_and_form_fields_appear_on_next_read(self) -> None:
        """Include live extensions, accurate parameters and ports without unsafe evaluation."""
        before = workflow_reference(self.request)
        definition = WorkflowNodeDefinition(
            "REFERENCE_EXTENSION",
            "ACTION",
            "Extension",
            "Custom node",
            ExtensionExecutor,
        )
        WORKFLOW_NODE_REGISTRY.register("reference-extension-key", definition)
        self.addCleanup(WORKFLOW_NODE_REGISTRY.unregister, "reference-extension-key")
        after = workflow_reference(self.request)
        self.assertEqual(len(after["nodes"]), len(before["nodes"]) + 1)
        self.assertEqual(
            {item["sub_type"] for item in after["nodes"]},
            {node.id for node in WORKFLOW_NODE_REGISTRY.values()},
        )
        node = next(
            item for item in after["nodes"] if item["sub_type"] == definition.id
        )
        fields = {field["name"]: field for field in node["parameters"]}
        self.assertEqual(fields["count"]["initial"], 3)
        self.assertEqual(fields["count"]["min_value"], 1)
        self.assertEqual(fields["count"]["help_text"], "Number of items")
        self.assertEqual(fields["count"]["form_field_type"], "IntegerField")
        self.assertFalse(fields["mode"]["required"])
        self.assertEqual(fields["mode"]["choices"], [["one", "One"], ["two", "Two"]])
        self.assertEqual(
            fields["recipient"]["choices_status"], "user_scoped_not_enumerated"
        )
        self.assertEqual(
            fields["lazy_choice"]["choices_status"], "dynamic_not_evaluated"
        )
        self.assertEqual(fields["dynamic"]["default_status"], "dynamic_not_evaluated")
        self.assertEqual(
            node["output_ports"],
            [{"id": "custom", "label": "Custom output", "max_connections": 2}],
        )
        self.assertNotIn("must-never-leak", json.dumps(after))

    def test_choice_widgets_and_metadata_only_nodes(self) -> None:
        """Include widget-only static choices and nodes that have no executor."""
        field = forms.CharField(widget=forms.Select(choices=[("GET", "GET")]))
        self.assertEqual(field_reference("method", field)["choices"], [["GET", "GET"]])
        WORKFLOW_NODE_REGISTRY.register(
            "reference-no-executor",
            WorkflowNodeDefinition(
                "REFERENCE_NO_EXECUTOR", "ACTION", "Metadata", "No executor"
            ),
        )
        self.addCleanup(WORKFLOW_NODE_REGISTRY.unregister, "reference-no-executor")
        node = next(
            item
            for item in workflow_reference(self.request)["nodes"]
            if item["sub_type"] == "REFERENCE_NO_EXECUTOR"
        )
        self.assertEqual(node["configuration_status"], "no_executor_declared")

    def test_nested_defaults_and_credential_choices_are_redacted(self) -> None:
        """Avoid publishing credentials nested in otherwise useful JSON defaults."""
        field = forms.JSONField(
            initial={
                "headers": {"Authorization": "private", "Accept": "application/json"}
            }
        )
        result = field_reference("options", field)
        self.assertIsNone(result["initial"]["headers"]["Authorization"])
        self.assertEqual(result["initial"]["headers"]["Accept"], "application/json")
        credential = forms.ChoiceField(choices=[("private", "Credential")])
        result = field_reference("api_key", credential)
        self.assertNotIn("choices", result)
        self.assertEqual(result["choices_status"], "omitted_sensitive")

    def test_custom_schema_factories_are_marked_without_evaluation(self) -> None:
        """Distinguish inherited declarations from nodes with configuration-specific schemas."""
        nodes = {
            node["sub_type"]: node for node in workflow_reference(self.request)["nodes"]
        }
        self.assertIn(
            "get_input_requirement",
            nodes["HUMAN_TRIGGER"]["metadata_factory_overrides"],
        )
        self.assertIn("get_output_schema", nodes["WAIT"]["metadata_factory_overrides"])

    def test_readers_reject_anonymous_direct_calls(self) -> None:
        """Keep reader authentication effective independently of the MCP endpoint."""
        self.request.user = AnonymousUser()
        for reader in (workflow_reference, policy_reference):
            with (
                self.subTest(reader=reader.__name__),
                self.assertRaises(PermissionDenied),
            ):
                reader(self.request)

    def test_workflow_guide_example_matches_graph_serializer_and_node_forms(
        self,
    ) -> None:
        """Validate the documented graph and parameters without saving or executing it."""
        guide = workflow_reference(self.request)["guide"]
        example = json.loads(guide.split("```json\n", 1)[1].split("```", 1)[0])
        serializer = WorkflowSerializer(data=example)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        for node in example["nodes"]:
            form_class = WORKFLOW_NODE_REGISTRY.get(
                node["sub_type"]
            ).executor_cls.config_form
            self.assertTrue(set(node["parameters"]).issubset(form_class.base_fields))
        self.assertIn("no registered dedicated create_workflow MCP tool", guide)

    def test_policy_guide_tracks_current_serializer_and_permission_schema(self) -> None:
        """Verify current permission vocabulary, filter structure and nested API names."""
        guide = policy_reference(self.request)
        example = json.loads(guide.split("```json\n", 1)[1].split("```", 1)[0])
        self.assertEqual(set(example) - set(PolicySerializer.Meta.fields), set())
        rule = example["row_policy"]["rules"][0]
        parsed = RowPolicyRuleContent.model_validate(rule["rule"])
        self.assertEqual(parsed.connector, "AND")
        self.assertEqual(rule["permissions"], example["global_permissions"])
        self.assertEqual(
            example["field_policy"]["rules"]["__all__"], example["global_permissions"]
        )
        metadata = json.loads(guide.rsplit("```json\n", 1)[1].split("```", 1)[0])
        self.assertEqual(
            [item["action"] for item in metadata["model_permissions"]],
            [item.value.codename for item in BloomerpPermission],
        )
        self.assertEqual(
            metadata["row_rule_schema"], RowPolicyRuleContent.model_json_schema()
        )
        self.assertIn("PolicySerializer does not accept users or groups", guide)
        self.assertIn("field_path", guide)
        self.assertIn("IsAdminUser", guide)


@override_settings(
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["testserver"],
    BLOOMERP_CONFIG=BloomerpConfig(
        auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))
    ),
)
class AuthoringReferenceRequestTests(RequestTestCaseMixin, TestCase):
    """Use the repository request scenarios for MCP discovery/read authorization."""

    view_name = "authoring_reference_mcp"

    def setUp(self) -> None:
        """Create an ordinary reader and keep unrelated tools out of discovery."""
        super().setUp()
        self.reader = get_user_model().objects.create_user(
            username="reference-reader", password="test-password"
        )
        self.enterContext(patch.object(router, "get_mcp_routes", return_value=[]))

    def rpc_payload(self, method: str, uri: str | None = None) -> dict[str, Any]:
        """Build a JSON-RPC request for a documented MCP operation."""
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {"uri": uri} if uri else {},
        }

    def catalog_contains_references(self, response: HttpResponse) -> bool:
        """Check discovery advertises both identities without resource contents."""
        entries = response.json()["result"]["resources"]
        uris = {item["uri"] for item in entries}
        return {
            "bloomerp://guides/create-workflow",
            "bloomerp://guides/create-policy",
        }.issubset(uris) and all("text" not in entry for entry in entries)

    def workflow_read_is_live(self, response: HttpResponse) -> bool:
        """Check an authenticated transport read serializes every installed node."""
        content = response.json()["result"]["contents"][0]
        document = json.loads(content["text"])
        return content["mimeType"] == "application/json" and {
            node["sub_type"] for node in document["nodes"]
        } == {node.id for node in WORKFLOW_NODE_REGISTRY.values()}

    def policy_read_is_current(self, response: HttpResponse) -> bool:
        """Check the Markdown guide arrives through the production resource transport."""
        content = response.json()["result"]["contents"][0]
        return (
            content["mimeType"] == "text/markdown"
            and "ApiAccessResolver" in content["text"]
            and "assign_group" in content["text"]
        )

    def test_policy_example_validates_through_current_policy_serializer(self) -> None:
        """Substitute real target metadata and validate the guide's nested policy payload."""
        request = HttpRequest()
        request.user = self.reader
        example = json.loads(
            policy_reference(request).split("```json\n", 1)[1].split("```", 1)[0]
        )
        content_type = ContentType.objects.get_for_model(Workflow)
        Permission.objects.get_or_create(
            content_type=content_type,
            codename="view_workflow",
            defaults={"name": "View workflow"},
        )
        example["content_type_id"] = content_type.pk
        example["global_permissions"] = ["view_workflow"]
        example["row_policy"]["rules"][0]["permissions"] = ["view_workflow"]
        example["field_policy"]["rules"] = {"__all__": ["view_workflow"]}
        serializer = PolicySerializer(data=example)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover catalog discovery, ordinary-user reads and anonymous read rejection."""
        scenarios = [
            RequestScenario(
                name="Authenticated catalog discovery",
                user=self.reader,
                data=self.rpc_payload("resources/list"),
                expected=ExpectedResult(
                    response_validators=self.catalog_contains_references
                ),
            ),
            RequestScenario(
                name="OAuth catalog discovery before account linking",
                data=self.rpc_payload("resources/list"),
                expected=ExpectedResult(
                    response_validators=self.catalog_contains_references
                ),
            ),
        ]
        for uri, validator in (
            ("bloomerp://guides/create-workflow", self.workflow_read_is_live),
            ("bloomerp://guides/create-policy", self.policy_read_is_current),
        ):
            scenarios.append(
                RequestScenario(
                    name=f"Ordinary user reads {uri}",
                    user=self.reader,
                    data=self.rpc_payload("resources/read", uri),
                    expected=ExpectedResult(response_validators=validator),
                )
            )
            scenarios.append(
                RequestScenario(
                    name=f"Anonymous cannot read {uri}",
                    data=self.rpc_payload("resources/read", uri),
                    expected=ExpectedResult(status_code=401),
                )
            )
        for scenario in scenarios:
            scenario.method = "POST"
            scenario.content_type = "application/json"
            scenario.headers = {"accept": "application/json, text/event-stream"}
        return scenarios
