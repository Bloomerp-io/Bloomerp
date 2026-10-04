"""BloomAI navigation and permission-aware monitoring of logical agent runs."""

from typing import ClassVar

from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.workspaces.base import BaseTileConfig
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig

from .definition import BloomerpModule, ModuleConfig

QUICK_ACCESS_TILE = LinkTileConfig(
    id="bloomai:quick_access",
    name="Quick access",
    icon="fa fa-link",
    links=[
        Link(name="Create AI Agent", url_name="ai_agents_add"),
        Link(name="View AI Agents", url_name="ai_agents_model"),
        Link(name="Create MCP Integration", url_name="mcp_integrations_add"),
        Link(name="View MCP Integrations", url_name="mcp_integrations_model"),
    ],
)


def monitoring_tiles() -> list[BaseTileConfig]:
    """Build usage analytics after model loading, counting logical runs and calls once."""
    # Analytics renderers import SQL services and Django models; defer their
    # import because agent models themselves import the BloomAI module.
    from bloomerp.workspaces.analytics_tile.model import (
        AnalyticsTileConfig,
        FieldConfig,
    )

    input_tokens = "CAST(COALESCE(usage ->> 'input_tokens', '0') AS BIGINT)"
    output_tokens = "CAST(COALESCE(usage ->> 'output_tokens', '0') AS BIGINT)"
    total_tokens = f"({input_tokens} + {output_tokens})"
    tool_calls = "CAST(COALESCE(usage ->> 'tool_calls', '0') AS BIGINT)"
    return [
        AnalyticsTileConfig(
            id="bloomai:total_tokens",
            name="Total tokens",
            description="All-time input and output tokens across visible runs, including retries.",
            icon="fa-solid fa-coins",
            type="KPI",
            query=f"SELECT COALESCE(SUM({total_tokens}), 0) AS tokens FROM bloomerp_ai_run",
            fields={
                "value": [FieldConfig(name="tokens", opts={"formatter": "INTEGER"})]
            },
            opts={
                "advanced_formatting_value": "{% load humanize %}{{ value|intcomma }}"
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:tokens_per_user",
            name="Tokens per active user",
            description="Average all-time tokens per user who initiated at least one visible run.",
            icon="fa-solid fa-user",
            type="KPI",
            query=f"""SELECT COALESCE(AVG(user_tokens), 0) AS tokens
                FROM (SELECT initiated_by_id, SUM({total_tokens}) AS user_tokens
                      FROM bloomerp_ai_run GROUP BY initiated_by_id) AS active_users""",
            fields={
                "value": [FieldConfig(name="tokens", opts={"formatter": "INTEGER"})]
            },
            opts={
                "advanced_formatting_value": "{% load humanize %}{{ value|intcomma }}"
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:run_count",
            name="Total runs",
            description="All-time visible logical runs; retries belong to the same run.",
            icon="fa-solid fa-play",
            type="KPI",
            query="""SELECT COUNT(*) AS runs,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed
                FROM bloomerp_ai_run""",
            fields={
                "value": [FieldConfig(name="runs", opts={"formatter": "INTEGER"})],
                "sub_value": [
                    FieldConfig(
                        name="failed",
                        opts={"formatter": "INTEGER", "suffix": " failed"},
                    )
                ],
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:active_runs",
            name="Active runs",
            description="Queued, running, and waiting runs currently visible to you.",
            icon="fa-solid fa-spinner",
            type="KPI",
            query="""SELECT
                COALESCE(SUM(CASE WHEN status IN ('queued', 'running', 'waiting') THEN 1 ELSE 0 END), 0) AS active,
                COALESCE(SUM(CASE WHEN status = 'waiting' THEN 1 ELSE 0 END), 0) AS waiting
                FROM bloomerp_ai_run""",
            fields={
                "value": [FieldConfig(name="active", opts={"formatter": "INTEGER"})],
                "sub_value": [
                    FieldConfig(
                        name="waiting",
                        opts={"formatter": "INTEGER", "suffix": " waiting"},
                    )
                ],
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:daily_usage",
            name="Daily token usage",
            description="Input and output token totals grouped by the date each run was created.",
            icon="fa-solid fa-chart-line",
            type="TWO_DIM_CHART",
            query=f"""SELECT DATE(datetime_created) AS day,
                {input_tokens} AS input_tokens, {output_tokens} AS output_tokens
                FROM bloomerp_ai_run""",
            fields={
                "x_axis": [FieldConfig(name="day", opts={"label": "Date"})],
                "y_axis": [
                    FieldConfig(name="input_tokens", opts={"label": "Input tokens"}),
                    FieldConfig(name="output_tokens", opts={"label": "Output tokens"}),
                ],
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:run_status",
            name="Run status",
            description="All-time distribution of visible runs by their current status.",
            icon="fa-solid fa-chart-pie",
            type="PIE_CHART",
            query="SELECT status, 1 AS runs FROM bloomerp_ai_run",
            fields={
                "labels": [FieldConfig(name="status", opts={"label": "Status"})],
                "values": [FieldConfig(name="runs", opts={"label": "Runs"})],
            },
        ),
        AnalyticsTileConfig(
            id="bloomai:tool_usage",
            name="Tool usage",
            description="All-time dispatched visible tool calls, counted once per logical action; pending and rejected proposals are excluded.",
            icon="fa-solid fa-screwdriver-wrench",
            type="TABLE",
            query="""SELECT COALESCE(MAX(NULLIF(tool_title, '')), tool_identifier) AS tool,
                tool_identifier, COUNT(*) AS calls
                FROM bloomerp_ai_tool_call WHERE started_at IS NOT NULL
                GROUP BY tool_identifier
                ORDER BY calls DESC, tool_identifier""",
            fields={
                "columns": [
                    FieldConfig(name="tool", opts={"label": "Tool"}),
                    FieldConfig(name="tool_identifier", opts={"label": "Identifier"}),
                    FieldConfig(
                        name="calls", opts={"label": "Calls", "formatter": "INTEGER"}
                    ),
                ]
            },
            opts={"page_size": 10},
        ),
        AnalyticsTileConfig(
            id="bloomai:recent_runs",
            name="Recent runs",
            description="The latest 50 visible runs with provider, model, and cumulative usage.",
            icon="fa-solid fa-clock-rotate-left",
            type="TABLE",
            query=f"""SELECT id, datetime_created, status,
                config_snapshot ->> 'provider' AS provider,
                config_snapshot ->> 'model' AS model_identifier,
                {total_tokens} AS total_tokens, {tool_calls} AS tool_calls
                FROM bloomerp_ai_run ORDER BY datetime_created DESC, id DESC LIMIT 50""",
            fields={
                "columns": [
                    FieldConfig(name="datetime_created", opts={"label": "Started"}),
                    FieldConfig(name="status", opts={"label": "Status"}),
                    FieldConfig(name="provider", opts={"label": "Provider"}),
                    FieldConfig(name="model_identifier", opts={"label": "Model"}),
                    FieldConfig(name="total_tokens", opts={"label": "Tokens"}),
                    FieldConfig(name="tool_calls", opts={"label": "Tool calls"}),
                    FieldConfig(name="id", opts={"label": "Run ID"}),
                ]
            },
            opts={"page_size": 10},
        ),
    ]


class BloomAIModule(BloomerpModule):
    """Expose agent management alongside usage and execution monitoring."""

    id = "bloomai"
    code = "bloomai"
    icon = "fa-solid fa-robot"
    name = "BloomAI"
    description = "Manage your agents and monitor token usage and runs."
    tiles: ClassVar[list[BaseTileConfig]] = [QUICK_ACCESS_TILE]
    workspaces: ClassVar[list[WorkspaceLayout]] = [
        WorkspaceLayout(
            name="BloomAI",
            is_default=True,
            rows=[
                LayoutRow(
                    columns=1,
                    title="Quick Access",
                    items=[LayoutItem(id="bloomai:quick_access")],
                ),
                LayoutRow(
                    columns=4,
                    title="Usage and runs",
                    items=[
                        LayoutItem(id="bloomai:total_tokens"),
                        LayoutItem(id="bloomai:tokens_per_user"),
                        LayoutItem(id="bloomai:run_count"),
                        LayoutItem(id="bloomai:active_runs"),
                    ],
                ),
                LayoutRow(
                    columns=2,
                    title="Activity",
                    items=[
                        LayoutItem(id="bloomai:daily_usage"),
                        LayoutItem(id="bloomai:run_status"),
                    ],
                ),
                LayoutRow(
                    columns=1,
                    title="Tool usage",
                    items=[LayoutItem(id="bloomai:tool_usage")],
                ),
                LayoutRow(
                    columns=1,
                    title="Recent runs",
                    items=[LayoutItem(id="bloomai:recent_runs")],
                ),
            ],
        ),
    ]

    @classmethod
    def to_config(cls, *, owner_app_label: str | None = None) -> ModuleConfig:
        """Resolve analytics after Django models load and validate the workspace."""
        cls.tiles = [QUICK_ACCESS_TILE, *monitoring_tiles()]
        return super().to_config(owner_app_label=owner_app_label)
