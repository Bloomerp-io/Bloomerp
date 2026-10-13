from bloomerp.models.definition import LayoutItem, LayoutRow, WorkspaceLayout
from bloomerp.workspaces.links_tile.model import Link, LinkTileConfig

from .definition import BloomerpModule

class AutomationModule(BloomerpModule):
    id = "automation"
    code = "automation"
    icon = "fa-solid fa-hexagon-nodes"
    name = "Automation"
    description = "With automation, streamline and optimize your business processes by creating automated workflows."

    tiles = [
        LinkTileConfig(
            id="automation:quick-access",
            name="Build & manage",
            description="Create and manage automation workflows.",
            icon="fa-solid fa-diagram-project",
            links=[
                Link(
                    name="View all workflows",
                    url_name="workflows_model",
                    is_internal=True,
                ),
                Link(
                    name="Create a workflow",
                    url_name="workflows_add",
                    is_internal=True,
                ),
            ]
        ),
        LinkTileConfig(
            id="automation:monitoring-links",
            name="Monitor & intervene",
            description="Inspect workflow execution and runs requiring intervention.",
            icon="fa-solid fa-heart-pulse",
            links=[
                Link(
                    name="View all workflow runs",
                    url_name="workflow_runs_model",
                    is_internal=True,
                ),
            ],
        ),
    ]

    workspaces = [
        WorkspaceLayout(
            name="Automations Overview",
            is_default=True,
            rows=[
                LayoutRow(
                    columns=4,
                    title="At a glance",
                    items=[
                        LayoutItem(id="workflow:number_of_workflows"),
                        LayoutItem(id="workflow_run:number_of_runs"),
                        LayoutItem(id="workflow_run:success_rate"),
                        LayoutItem(id="workflow_run:runs_pending_action"),
                    ],
                ),
                LayoutRow(
                    title="Quick Access",
                    columns=2,
                    items=[
                        LayoutItem(id="automation:quick-access"),
                        LayoutItem(id="automation:monitoring-links"),
                    ],
                ),
                LayoutRow(
                    title="Operational health",
                    columns=2,
                    items=[
                        LayoutItem(id="workflow_run:status_distribution"),
                        LayoutItem(id="workflow_run:run_trend"),
                    ],
                ),
                LayoutRow(
                    title="Attention required",
                    columns=1,
                    items=[
                        LayoutItem(id="workflow_run:last_runs"),
                    ],
                ),
                LayoutRow(
                    title="Performance and usage",
                    columns=2,
                    items=[
                        LayoutItem(id="workflow_run:runs_by_workflow"),
                        LayoutItem(id="workflow_run:average_duration_by_workflow"),
                    ],
                ),
                LayoutRow(
                    title="Workflow hygiene",
                    columns=1,
                    items=[
                        LayoutItem(id="workflow:configuration_attention"),
                    ],
                ),
            ],
        )
    ]
