from typing import TYPE_CHECKING
from django.db import models
from django.urls import reverse
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig, DetailViewSettings, ObjectModalAction
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _, gettext_noop
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType, FieldConfig

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_node import WorkflowNode
    from bloomerp.models.automation.workflow_edge import WorkflowEdge


class Workflow(
    UserStampModelMixin,
    TimestampModelMixin,
    AbsoluteUrlModelMixin,
    models.Model
    ):
    """
    A workflow is a model for automation.
    Each workflow can have differnent nodes.
    """
    class Meta:
        db_table = "bloomerp_workflow"
        verbose_name = _("Workflow")
        verbose_name_plural = _("Workflows")
    
    bloomerp_config = BloomerpModelConfig(
        module="automation",
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                LayoutRow(
                    title=gettext_noop("Details"),
                    columns=2,
                    items=[
                        LayoutItem(id="name")
                    ]
                ),
                LayoutRow(
                    title=gettext_noop("Configuration"),
                    columns=2,
                    items=[
                        LayoutItem(id="active"),
                        LayoutItem(id="run_asynchronously"),
                        LayoutItem(id="enable_logging"),
                    ]
                ),
                ]
            )],
            skip_views=["document_templates", "files"],
        ),
        object_actions=[
            ObjectModalAction(
                id="run_workflow",
                label=gettext_noop("Run workflow"),
                endpoint=lambda obj: reverse("components_automation_run_workflow", kwargs={"workflow_id" : obj.id}),
                modal_title=gettext_noop("Run workflow")
            ),
            
        ],
        create_redirect_url_func=lambda x: reverse(
            "workflows_detail_builder",
            kwargs={"pk":x.pk}
        ),
        tiles=[
            AnalyticsTileConfig(
                id="workflow:number_of_workflows",
                type=AnalyticsTileType.KPI.value.key,
                name="Active workflows",
                description="Active workflows, with the total number of workflows shown below.",
                icon="fa-solid fa-robot",
                query="""
                    SELECT
                        COALESCE(SUM(CASE WHEN active THEN 1 ELSE 0 END), 0) AS active_count,
                        COUNT(*) AS total_count
                    FROM bloomerp_workflow
                """,
                fields={
                    "value": [
                        FieldConfig(
                            name="active_count",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "INTEGER",
                            },
                        )
                    ],
                    "sub_value": [
                        FieldConfig(
                            name="total_count",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "INTEGER",
                                "suffix": " total",
                            },
                        )
                    ],
                },
            ),
            AnalyticsTileConfig(
                id="workflow:configuration_attention",
                type=AnalyticsTileType.TABLE.value.key,
                name="Workflow configuration attention",
                description="Inactive workflows, workflows without a trigger, and workflows that have never run.",
                icon="fa-solid fa-screwdriver-wrench",
                query="""
                    SELECT
                        workflow.id AS workflow_id,
                        workflow.name AS workflow_name,
                        CASE
                            WHEN NOT workflow.active THEN 'Inactive'
                            WHEN NOT EXISTS (
                                SELECT 1
                                FROM bloomerp_workflow_node node
                                WHERE node.workflow_id = workflow.id
                                  AND node.type = 'TRIGGER'
                            ) THEN 'Missing trigger'
                            ELSE 'Never run'
                        END AS issue
                    FROM bloomerp_workflow workflow
                    WHERE NOT workflow.active
                       OR NOT EXISTS (
                            SELECT 1
                            FROM bloomerp_workflow_node node
                            WHERE node.workflow_id = workflow.id
                              AND node.type = 'TRIGGER'
                       )
                       OR NOT EXISTS (
                            SELECT 1
                            FROM bloomerp_workflow_run run
                            WHERE run.workflow_id = workflow.id
                       )
                    ORDER BY workflow.name
                """,
                fields={
                    "columns": [
                        FieldConfig(
                            name="workflow_name",
                            opts={
                                "label": "Workflow",
                                "advanced_formatting": """<a href="{% url 'workflows_detail_overview' pk=var_workflow_id %}">{{ var_workflow_name }}</a>""",
                            },
                        ),
                        FieldConfig(name="issue", opts={"label": "Issue"}),
                    ]
                },
                opts={"page_size": 10},
            ),
        ]
    )
    
    name = models.CharField(
        max_length=255,
        help_text=_("The name of the workflow."),
        verbose_name=_("Name")
        )
    run_asynchronously = models.BooleanField(
        default=False,
        help_text=_("Whether runs asynchronously"),
        verbose_name=_("Run Asynchronously")
    )
    active = models.BooleanField(
        default=True,
        help_text=_("Whether the workflow is active or not"),
        verbose_name=_("Active")
    )
    enable_logging = models.BooleanField(
        default=False,
        help_text=_("Whether to enable logging for this workflow. Disabling logging may improve performance but will result in no detailed execution history being stored."),
        verbose_name=_("Enable Logging")
    )
    
    def get_trigger(self) -> "WorkflowNode |None":
        """Returns the trigger of a workflow.

        Returns:
            WorkflowNode: the triggering node of this workflow
        """
        nodes: models.QuerySet["WorkflowNode"] = self.nodes.all()

        return nodes.filter(
            type="TRIGGER"
        ).first()

    def __str__(self) -> str:
        return self.name    
        
    def contains_node(self, node:"WorkflowNode") -> bool:
        """Checks whether a workflow contains a node object

        Args:
            node (WorkflowNode): the node to check for

        Returns:
            bool: whether it contains the node
        """
        return self.nodes.filter(id=node.id).exists()
    
    def connect_nodes(
        self,
        from_node: "WorkflowNode",
        to_node: "WorkflowNode",
        *,
        output_port: str = "default",
    ) -> "WorkflowEdge":
        """Adds a connection between two nodes.

        Args:
            input_node (WorkflowNode): the input node
            output_node (WorkflowNode): the output node 
        
        Returns:
            edge : the edge between the two nodes
        """
        from bloomerp.models.automation.workflow_edge import WorkflowEdge
        if not self.contains_node(from_node) or not self.contains_node(to_node):
            raise ValueError("Node not in workflow")

        return WorkflowEdge.objects.create(
            from_node=from_node,
            to_node=to_node,
            output_port=output_port,
        )
