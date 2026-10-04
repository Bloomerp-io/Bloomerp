"""Verify BloomAI monitoring queries, accounting, layout, and SQL authorization."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from bloomerp.filters.definition import FilterCondition
from bloomerp.models.agents import AIConversation, AIMessage, AIRun, AIToolCall
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.modules.bloomai import BloomAIModule, monitoring_tiles
from bloomerp.permissions.definition import (
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.services.workspace_services import (
    _serialize_default_tile_config,
    resolve_tile_type_from_config,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.workspaces.analytics_tile.kpi import build_kpi_aggregation_query
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.analytics_tile.pie_chart import build_pie_chart_query
from bloomerp.workspaces.analytics_tile.render import AnalyticsTileRenderer


class BloomAIMonitoringTests(BloomerpComponentTestCase):
    """Execute configured analytics through the same permission boundary as tiles."""

    view_name = "components_render_layout_item"

    auto_create_customers = False
    auto_create_users = False

    def extendedSetup(self) -> None:
        """Create monitoring actors and resolve the declarative analytics tiles."""
        self.admin = get_user_model().objects.create_user(
            username="monitor-admin", is_superuser=True
        )
        self.owner = get_user_model().objects.create_user(username="monitor-owner")
        self.other = get_user_model().objects.create_user(username="monitor-other")
        self.tiles = {tile.id: tile for tile in monitoring_tiles()}
        content_type = ContentType.objects.get_for_model(AIRun)
        for field in AIRun._meta.fields:
            ApplicationField.objects.get_or_create(
                content_type=content_type,
                field=field.name,
                defaults={"field_type": field.get_internal_type()},
            )

    def make_run(
        self, owner: AbstractBloomerpUser, status: str, tokens: int = 0
    ) -> AIRun:
        """Create an independent logical run with cumulative input/output usage."""
        conversation = AIConversation.objects.create(owner=owner)
        message = AIMessage.objects.create(
            conversation=conversation,
            sequence=1,
            role="user",
            content_blocks=[{"type": "text", "text": "Private conversation"}],
        )
        return AIRun.objects.create(
            conversation=conversation,
            trigger_message=message,
            initiated_by=owner,
            agent_key="bloomai",
            agent_version="1",
            status=status,
            wait_condition={"kind": "user_input"} if status == "waiting" else None,
            config_snapshot={"runtime": "test", "provider": "test", "model": "example"},
            usage={
                "input_tokens": tokens,
                "output_tokens": tokens // 2,
                "tool_calls": 2,
            },
        )

    def query(
        self, tile_key: str, user: AbstractBloomerpUser | None = None
    ) -> list[dict[str, Any]]:
        """Execute a tile's source query as the administrator or supplied actor."""
        tile = self.tiles[f"bloomai:{tile_key}"]
        return (
            SqlExecutor(user or self.admin)
            .execute_query(tile.query, paginate=False)
            .rows
        )

    def test_layout_is_complete_and_repeatable(self) -> None:
        """Resolve every workspace item and avoid duplicate tiles on refresh."""
        config = BloomAIModule.to_config()
        self.assertEqual(len(config.tiles), 9)
        self.assertEqual(config, BloomAIModule.to_config())
        tile_ids = {tile.id for tile in config.tiles}
        for row in config.workspaces[0].rows:
            for item in row.items:
                self.assertIn(item.id, tile_ids)

    def test_empty_kpis_are_zero(self) -> None:
        """Show useful zero values when there are no runs yet."""
        for key in ("total_tokens", "tokens_per_user", "run_count", "active_runs"):
            with self.subTest(tile=key):
                tile = self.tiles[f"bloomai:{key}"]
                self.assertIsInstance(tile, AnalyticsTileConfig)
                fields = [field for group in tile.fields.values() for field in group]
                query, _ = build_kpi_aggregation_query(tile.query, fields)
                rows = SqlExecutor(self.admin).execute_query(query, paginate=False).rows
                self.assertTrue(all(value == 0 for value in rows[0].values()))

    def test_usage_counts_logical_runs_and_only_active_users(self) -> None:
        """Total cumulative run usage once and average over initiating users only."""
        self.make_run(self.owner, "completed", 100)
        self.make_run(self.owner, "failed", 200)
        self.make_run(self.other, "waiting", 300)
        self.make_run(self.other, "queued")
        self.make_run(self.other, "running")
        self.assertEqual(self.query("total_tokens"), [{"tokens": 900}])
        self.assertEqual(self.query("tokens_per_user"), [{"tokens": 450}])
        self.assertEqual(self.query("run_count"), [{"runs": 5, "failed": 1}])
        self.assertEqual(self.query("active_runs"), [{"active": 3, "waiting": 1}])
        rows = self.query("daily_usage")
        self.assertEqual(sum(row["input_tokens"] for row in rows), 600)
        self.assertEqual(sum(row["output_tokens"] for row in rows), 300)
        tile = self.tiles["bloomai:run_status"]
        query = build_pie_chart_query(
            tile.query, tile.fields["labels"][0], tile.fields["values"][0]
        )
        rows = SqlExecutor(self.admin).execute_query(query, paginate=False).rows
        self.assertEqual(sum(row["bloomerp_pie_value"] for row in rows), 5)
        recent = self.query("recent_runs")
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0]["model_identifier"], "example")
        self.assertNotIn("Private conversation", str(recent))

    def test_usage_respects_row_permissions(self) -> None:
        """Limit counts and JSON usage aggregates to the actor's granted run rows."""
        self.make_run(self.owner, "completed", 100)
        self.make_run(self.other, "failed", 900)
        policy = PolicyManager.create_policy(
            model_or_content_type=AIRun,
            field_permissions={
                "id": BloomerpPermission.VIEW,
                "usage": BloomerpPermission.VIEW,
                "status": BloomerpPermission.VIEW,
                "initiated_by": BloomerpPermission.VIEW,
            },
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="initiated_by",
                            operator="equals",
                            value=str(self.owner.pk),
                        )
                    ],
                )
            ],
        )
        policy.assign_user(self.owner)
        self.assertEqual(self.query("total_tokens", self.owner), [{"tokens": 150}])
        self.assertEqual(self.query("tokens_per_user", self.owner), [{"tokens": 150}])
        self.assertEqual(
            self.query("run_count", self.owner), [{"runs": 1, "failed": 0}]
        )

    def test_usage_requires_field_permissions(self) -> None:
        """Prevent usage disclosure when only the run status field is granted."""
        self.make_run(self.owner, "completed", 100)
        policy = PolicyManager.create_policy(
            model_or_content_type=AIRun,
            field_permissions={"status": BloomerpPermission.VIEW},
            row_permissions=[
                RowPolicyRuleContent(
                    conditions=[], permissions=[BloomerpPermission.VIEW]
                )
            ],
        )
        policy.assign_user(self.owner)
        self.assertEqual(self.query("total_tokens", self.owner), [{"tokens": 0}])
        with self.assertRaises(PermissionError):
            self.query("total_tokens", self.other)

    def test_every_analytics_tile_renders(self) -> None:
        """Exercise chart grouping, table pagination, and KPI template rendering."""
        self.make_run(self.owner, "completed", 100)
        for tile in self.tiles.values():
            with self.subTest(tile=tile.id):
                request = RequestFactory().get(
                    "/", {"tile_id": tile.id, "colspan": 1, "max_cols": 4}
                )
                request.user = self.admin
                rendered = AnalyticsTileRenderer.render(tile, request)
                self.assertTrue(rendered)
                self.assertNotIn("Private conversation", rendered)

    def prepare_tile_scenario(self, scenario: RequestScenario) -> None:
        """Seed visible and private calls and persist the requested native tile."""
        owned = self.make_run(self.owner, "completed", 1000000)
        private = self.make_run(self.other, "completed", 1000000)
        for model in (AIToolCall,):
            ct = ContentType.objects.get_for_model(model)
            for field in model._meta.fields:
                ApplicationField.objects.get_or_create(
                    content_type=ct,
                    field=field.name,
                    defaults={"field_type": field.get_internal_type()},
                )
        for run, identifier, title, status, dispatched in (
            (owned, "external.crm.search", "CRM: Search contacts", "completed", True),
            (owned, "external.crm.search", "CRM: Search contacts", "failed", True),
            (owned, "legacy_tool", "", "completed", True),
            (owned, "external.crm.search", "CRM: Search contacts", "waiting", False),
            (owned, "rejected_tool", "Rejected proposal", "rejected", False),
            (private, "private_tool", "Private tool", "completed", True),
        ):
            AIToolCall.objects.create(
                run=run,
                tool_identifier=identifier,
                tool_version="1",
                tool_title=title,
                provider_call_id=f"call-{AIToolCall.objects.count()}",
                status=status,
                started_at=timezone.now() if dispatched else None,
            )
        if scenario.user == self.owner:
            policy = PolicyManager.create_policy(
                model_or_content_type=AIToolCall,
                field_permissions={
                    field: BloomerpPermission.VIEW
                    for field in ("id", "tool_title", "tool_identifier", "started_at")
                    if field != "tool_title" or scenario.name != "tool_usage:redacted"
                },
                row_permissions=[
                    RowPolicyRuleContent(
                        permissions=[BloomerpPermission.VIEW],
                        conditions=[
                            FilterCondition(
                                field_path="run",
                                lookup_id="equals",
                                value=str(owned.pk),
                            )
                        ],
                    )
                ],
            )
            policy.assign_user(self.owner)
        key = scenario.name.split(":", 1)[0]
        config = next(
            tile
            for tile in BloomAIModule.to_config().tiles
            if tile.id == f"bloomai:{key}"
        )
        tile = Tile.objects.create(
            name=config.name,
            type=resolve_tile_type_from_config(config),
            schema=_serialize_default_tile_config(config),
            auto_generated=True,
        )
        scenario.query_params = {"tile_id": tile.pk, "colspan": 1, "max_cols": 4}
        scenario.view_kwargs = {
            "content_type_id": ContentType.objects.get_for_model(Workspace).pk
        }

    def validate_tool_usage(self, response: HttpResponse) -> bool:
        """Verify MCP labels, legacy fallback, counts and proposal exclusion."""
        rows = self.query("tool_usage")
        self.assertEqual(
            rows[0],
            {
                "tool": "CRM: Search contacts",
                "tool_identifier": "external.crm.search",
                "calls": 2,
            },
        )
        self.assertEqual(sum(row["calls"] for row in rows), 4)
        content = response.content.decode()
        return (
            "CRM: Search contacts" in content
            and "legacy_tool" in content
            and "Rejected proposal" not in content
        )

    def validate_owned_tool_usage(self, response: HttpResponse) -> bool:
        """Verify row rules hide private names and counts in the rendered tile."""
        rows = self.query("tool_usage", self.owner)
        self.assertEqual(sum(row["calls"] for row in rows), 3)
        content = response.content.decode()
        return "CRM: Search contacts" in content and "Private tool" not in content

    def validate_denied_tool_usage(self, response: HttpResponse) -> bool:
        """Verify actors without grants cannot read tool usage via SQL or HTTP."""
        with self.assertRaises(PermissionError):
            self.query("tool_usage", self.other)
        content = response.content.decode()
        return "CRM: Search contacts" not in content and "Private tool" not in content

    def validate_redacted_tool_usage(self, response: HttpResponse) -> bool:
        """Hide ungranted readable titles while retaining granted tool identifiers."""
        rows = self.query("tool_usage", self.owner)
        self.assertEqual(sum(row["calls"] for row in rows), 3)
        self.assertEqual(rows[0]["tool"], "external.crm.search")
        content = response.content.decode()
        return (
            "CRM: Search contacts" not in content and "external.crm.search" in content
        )

    def validate_quick_access(self, response: HttpResponse) -> bool:
        """Verify both MCP routes resolve and the create link uses the wizard."""
        from bloomerp.views.agents.create_mcp_integration import (
            CreateMCPIntegrationView,
        )

        self.assertIs(
            resolve(reverse("mcp_integrations_add")).func.view_class,
            CreateMCPIntegrationView,
        )
        content = response.content.decode()
        return all(
            reverse(name) in content
            for name in ("mcp_integrations_add", "mcp_integrations_model")
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Check grouped token KPIs, MCP links and tool visibility through HTTP."""
        scenarios = [
            RequestScenario(
                name="total_tokens:grouped",
                user=self.admin,
                expected=ExpectedResult(
                    response_validators=self.contains_text("3,000,000")
                ),
            ),
            RequestScenario(
                name="tokens_per_user:grouped",
                user=self.admin,
                expected=ExpectedResult(
                    response_validators=self.contains_text("1,500,000")
                ),
            ),
            RequestScenario(
                name="quick_access:routes",
                user=self.admin,
                expected=ExpectedResult(response_validators=self.validate_quick_access),
            ),
            RequestScenario(
                name="tool_usage:all",
                user=self.admin,
                expected=ExpectedResult(response_validators=self.validate_tool_usage),
            ),
            RequestScenario(
                name="tool_usage:owned",
                user=self.owner,
                expected=ExpectedResult(
                    response_validators=self.validate_owned_tool_usage
                ),
            ),
            RequestScenario(
                name="tool_usage:denied",
                user=self.other,
                expected=ExpectedResult(
                    response_validators=self.validate_denied_tool_usage
                ),
            ),
            RequestScenario(
                name="tool_usage:redacted",
                user=self.owner,
                expected=ExpectedResult(
                    response_validators=self.validate_redacted_tool_usage
                ),
            ),
            RequestScenario(
                name="tool_usage:anonymous",
                expected=ExpectedResult(status_code=403),
            ),
        ]
        for scenario in scenarios:
            scenario.prepare = self.prepare_tile_scenario
        return scenarios
