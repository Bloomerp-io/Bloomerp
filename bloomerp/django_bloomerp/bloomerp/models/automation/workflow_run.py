from datetime import datetime
import json
from typing import TYPE_CHECKING, Any

from django.core.files.base import ContentFile
from django.db import connection, models
from django.urls import reverse
from bloomerp.models.automation import workflow
from bloomerp.models.automation.workflow_run_step import WorkflowRunStepStatus
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig, DetailViewSettings, ObjectModalAction
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _, gettext_noop
from django.db.models import Max, Min
from django.db.models import Case, IntegerField, Value, When

from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType, FieldConfig
from bloomerp.automation.serialization import OUTPUT_UNSET, serialize_workflow_value

if TYPE_CHECKING:
    from bloomerp.automation.workflow_state import WorkflowRunState
    from bloomerp.models.automation.workflow_node import WorkflowNode
    from bloomerp.models.automation.workflow_run_step import WorkflowRunStep


def _recent_datetime_predicate(column: str, days: int) -> str:
    if connection.vendor == "sqlite":
        return f"{column} >= datetime('now', '-{days} days')"
    return f"{column} >= CURRENT_TIMESTAMP - INTERVAL '{days} days'"


def _run_status_expression(run_alias: str = "run") -> str:
    """Return SQL matching the precedence used by ``WorkflowRun.status``."""
    return f"""
        CASE
            WHEN EXISTS (
                SELECT 1 FROM bloomerp_workflow_run_step paused_step
                WHERE paused_step.workflow_run_id = {run_alias}.id
                  AND paused_step.status = 'PAUSED'
            ) THEN 'Paused'
            WHEN EXISTS (
                SELECT 1 FROM bloomerp_workflow_run_step failed_step
                WHERE failed_step.workflow_run_id = {run_alias}.id
                  AND failed_step.status = 'FAILED'
            ) THEN 'Failed'
            WHEN EXISTS (
                SELECT 1 FROM bloomerp_workflow_run_step cancelled_step
                WHERE cancelled_step.workflow_run_id = {run_alias}.id
                  AND cancelled_step.status = 'CANCELLED'
            ) THEN 'Cancelled'
            ELSE 'Completed'
        END
    """


def _run_status_source(days: int | None = None) -> str:
    recent_clause = ""
    if days is not None:
        recent_clause = f"WHERE {_recent_datetime_predicate('run.datetime_created', days)}"
    return f"""
        SELECT
            run.id,
            run.workflow_id,
            run.datetime_created,
            {_run_status_expression('run')} AS status_label
        FROM bloomerp_workflow_run run
        {recent_clause}
    """


def _average_duration_by_workflow_query() -> str:
    if connection.vendor == "sqlite":
        duration_expression = (
            "(julianday(MAX(step.datetime_created)) "
            "- julianday(MIN(step.datetime_created))) * 1440.0"
        )
    else:
        duration_expression = (
            "EXTRACT(EPOCH FROM "
            "(MAX(step.datetime_created) - MIN(step.datetime_created))) / 60.0"
        )

    return f"""
        SELECT
            workflow.name AS workflow_name,
            AVG(run_duration.duration_minutes) AS duration_minutes
        FROM (
            SELECT
                run.id,
                run.workflow_id,
                {duration_expression} AS duration_minutes
            FROM bloomerp_workflow_run run
            INNER JOIN bloomerp_workflow_run_step step
                ON step.workflow_run_id = run.id
            WHERE {_recent_datetime_predicate('run.datetime_created', 30)}
            GROUP BY run.id, run.workflow_id
            HAVING COUNT(step.id) > 1
        ) run_duration
        INNER JOIN bloomerp_workflow workflow
            ON workflow.id = run_duration.workflow_id
        GROUP BY workflow.id, workflow.name
    """


class WorkflowRun(
    TimestampModelMixin,
    AbsoluteUrlModelMixin,
    models.Model):
    
    class Meta:
        db_table = "bloomerp_workflow_run"
        verbose_name = _("Workflow Run")
        verbose_name_plural = _("Workflow Runs")
    
    bloomerp_config = BloomerpModelConfig(
        module="automation",
        detail_view_settings=DetailViewSettings(
            layouts=[FieldLayout(
                rows=[
                LayoutRow(
                    columns=2,
                    items=[
                        LayoutItem(id="workflow"),
                        LayoutItem(id="datetime_created"),
                        LayoutItem(id="steps", colspan=2, config={
                            "inline_fields" : [
                                "sequence",
                                "action_id",
                                "status",
                                "datetime_created"
                            ]
                        })
                    ]
                )
                ]
            )],
            skip_views=["files", "document_templates"],
        ),
        object_actions=[
            ObjectModalAction(
                id="approve_step",
                label=gettext_noop("Approve"),
                endpoint=lambda obj: reverse(
                    "components_automation_approve_workflow_continuation",
                    kwargs={
                        "workflow_run_id" : obj.id
                    }
                ),
                should_render_func=lambda req, obj: obj.status == WorkflowRunStepStatus.PAUSED,
                modal_title=gettext_noop("Approve workflow continuation")
            )
        ],
        activity_log_settings=ActivityLogSettings(enabled=False),
        tiles=[
            AnalyticsTileConfig(
                id="workflow_run:number_of_runs",
                type=AnalyticsTileType.KPI.value.key,
                name="Runs in the last 7 days",
                description="Workflow runs started during the last seven days.",
                icon="fa-solid fa-play",
                query=f"""
                    SELECT COUNT(*) AS value
                    FROM bloomerp_workflow_run run
                    WHERE {_recent_datetime_predicate('run.datetime_created', 7)}
                """,
                fields={
                    "value": [
                        FieldConfig(
                            name="value",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "INTEGER",
                            },
                        )
                    ]
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:success_rate",
                type=AnalyticsTileType.KPI.value.key,
                name="30-day success rate",
                description="Completed runs as a share of terminal runs during the last 30 days.",
                icon="fa-solid fa-circle-check",
                query=f"""
                    SELECT COALESCE(
                        1.0 * SUM(CASE WHEN status_label = 'Completed' THEN 1 ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN status_label IN ('Completed', 'Failed', 'Cancelled') THEN 1 ELSE 0 END), 0),
                        0
                    ) AS success_rate
                    FROM ({_run_status_source(30)}) recent_runs
                """,
                fields={
                    "value": [
                        FieldConfig(
                            name="success_rate",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "PERCENTAGE",
                            },
                        )
                    ]
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:runs_pending_action",
                type=AnalyticsTileType.KPI.value.key,
                name="Runs requiring attention",
                description="Distinct paused or failed workflow runs requiring intervention.",
                icon="fa-solid fa-triangle-exclamation",
                query=f"""
                    SELECT COUNT(*) AS attention_count
                    FROM ({_run_status_source()}) runs
                    WHERE status_label IN ('Paused', 'Failed')
                """,
                fields={
                    "value": [
                        FieldConfig(
                            name="attention_count",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "INTEGER",
                            },
                        )
                    ]
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:status_distribution",
                type=AnalyticsTileType.PIE_CHART.value.key,
                name="Run outcomes",
                description="Workflow run outcomes during the last 30 days.",
                icon="fa-solid fa-chart-pie",
                query=f"""
                    SELECT status_label, 1 AS run_count
                    FROM ({_run_status_source(30)}) recent_runs
                """,
                fields={
                    "labels": [FieldConfig(name="status_label")],
                    "values": [
                        FieldConfig(
                            name="run_count",
                            opts={"label": "Runs", "formatter": "INTEGER"},
                        )
                    ],
                },
                opts={"show_legend": True, "legend_position": "right"},
            ),
            AnalyticsTileConfig(
                id="workflow_run:run_trend",
                type=AnalyticsTileType.TWO_DIM_CHART.value.key,
                name="Run trend",
                description="Daily completed and unsuccessful runs during the last 30 days.",
                icon="fa-solid fa-chart-line",
                query=f"""
                    SELECT
                        CAST(datetime_created AS DATE) AS run_date,
                        CASE WHEN status_label = 'Completed' THEN 1 ELSE 0 END AS completed_count,
                        CASE WHEN status_label IN ('Failed', 'Cancelled') THEN 1 ELSE 0 END AS unsuccessful_count
                    FROM ({_run_status_source(30)}) recent_runs
                """,
                fields={
                    "x_axis": [FieldConfig(name="run_date")],
                    "y_axis": [
                        FieldConfig(
                            name="completed_count",
                            opts={"label": "Completed", "color": "#10b981"},
                        ),
                        FieldConfig(
                            name="unsuccessful_count",
                            opts={"label": "Failed or cancelled", "color": "#ef4444"},
                        ),
                    ],
                },
                opts={
                    "chart_type": "line",
                    "x_axis_label": "Run date",
                    "show_legend": True,
                    "legend_position": "top",
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:runs_by_workflow",
                type=AnalyticsTileType.TWO_DIM_CHART.value.key,
                name="Runs by workflow",
                description="Workflow usage during the last 30 days.",
                icon="fa-solid fa-chart-column",
                query=f"""
                    SELECT workflow.name AS workflow_name, 1 AS run_count
                    FROM bloomerp_workflow_run run
                    INNER JOIN bloomerp_workflow workflow ON workflow.id = run.workflow_id
                    WHERE {_recent_datetime_predicate('run.datetime_created', 30)}
                """,
                fields={
                    "x_axis": [FieldConfig(name="workflow_name")],
                    "y_axis": [
                        FieldConfig(
                            name="run_count",
                            opts={"label": "Runs", "color": "#6366f1"},
                        )
                    ],
                },
                opts={
                    "chart_type": "bar",
                    "x_axis_label": "Workflow",
                    "show_legend": False,
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:average_duration_by_workflow",
                type=AnalyticsTileType.TWO_DIM_CHART.value.key,
                name="Average step-span duration",
                description="Average minutes between the first and last logged step, by workflow, during the last 30 days.",
                icon="fa-solid fa-stopwatch",
                query=_average_duration_by_workflow_query(),
                fields={
                    "x_axis": [FieldConfig(name="workflow_name")],
                    "y_axis": [
                        FieldConfig(
                            name="duration_minutes",
                            opts={"label": "Minutes", "color": "#f59e0b"},
                        )
                    ],
                },
                opts={
                    "chart_type": "bar",
                    "x_axis_label": "Workflow",
                    "y_axis_label": "Minutes",
                    "show_legend": False,
                },
            ),
            AnalyticsTileConfig(
                id="workflow_run:last_runs",
                type=AnalyticsTileType.TABLE.value.key,
                name="Recent runs requiring attention",
                description="Paused and failed runs, with their most relevant action.",
                icon="fa-solid fa-list-check",
                query=f"""
                    SELECT
                        run.id AS run_id,
                        workflow.name AS workflow_name,
                        run.datetime_created,
                        {_run_status_expression('run')} AS status_label,
                        (
                            SELECT attention_step.action_id
                            FROM bloomerp_workflow_run_step attention_step
                            WHERE attention_step.workflow_run_id = run.id
                              AND attention_step.status IN ('PAUSED', 'FAILED')
                            ORDER BY
                                CASE attention_step.status
                                    WHEN 'PAUSED' THEN 1
                                    ELSE 2
                                END,
                                attention_step.datetime_created DESC
                            LIMIT 1
                        ) AS action_id
                    FROM bloomerp_workflow_run run
                    INNER JOIN bloomerp_workflow workflow ON workflow.id = run.workflow_id
                    WHERE {_run_status_expression('run')} IN ('Paused', 'Failed')
                    ORDER BY run.datetime_created DESC
                """,
                fields={
                    "columns": [
                        FieldConfig(
                            name="workflow_name",
                            opts={
                                "label": "Workflow",
                                "advanced_formatting": """<a href="{% url 'workflow_runs_detail_overview' pk=var_run_id %}">{{ var_workflow_name }}</a>""",
                            },
                        ),
                        FieldConfig(name="datetime_created", opts={"label": "Started"}),
                        FieldConfig(name="status_label", opts={"label": "Status"}),
                        FieldConfig(name="action_id", opts={"label": "Action"}),
                    ]
                },
                opts={"page_size": 10},
            ),
        ]
    )
    
    workflow = models.ForeignKey(
        workflow.Workflow,
        on_delete=models.CASCADE,
        help_text=_("The workflow associated with this run."),
        editable=False,
        related_name="runs",
        verbose_name=_("Workflow"),
    )
    
    def __str__(self):
        return f"{self.workflow.name} - {self.datetime_created}"

    def create_step(
        self,
        *,
        node: "WorkflowNode",
        sequence: int,
        status: WorkflowRunStepStatus,
        state: "WorkflowRunState",
        enabled: bool,
        output_data: Any = OUTPUT_UNSET,
    ) -> "WorkflowRunStep | None":
        """Persist one workflow step and its resumable execution state."""
        if not enabled:
            return None

        from bloomerp.models.automation.workflow_run_step import WorkflowRunStep

        step = WorkflowRunStep(
            workflow_run=self,
            sequence=sequence,
            action_id=node.node_sub_type_id or str(node.id),
            status=status,
            node=node,
        )
        if output_data is not OUTPUT_UNSET:
            serialized_output = serialize_workflow_value(output_data)
            step.output_file.save(
                f"workflow-run-{self.pk}-step-{sequence}.json",
                ContentFile(json.dumps(serialized_output).encode("utf-8")),
                save=False,
            )
        step.save()
        state.current_step_id = step.id
        step.state = state.model_dump(mode="json")
        step.save(update_fields=["state", "datetime_updated"])
        return step


    @property
    def execution_time(self) -> datetime:
        """Returns the execution time of the workflow

        Returns:
            datetime: the time it took for the workflow to run
        """
        timestamps = self.steps.aggregate(
            started_at=Min("datetime_created"),
            finished_at=Max("datetime_created"),
        )

        return (
            timestamps["finished_at"] - timestamps["started_at"]
            if timestamps["started_at"] and timestamps["finished_at"]
            else None
        )
            
    @property
    def number_of_steps(self):
        """Returns there were in the workflow
        """
        return self.steps.all().count()
    
    @property
    def status(self) -> str:
        """Returns the status of the workflow run step

        Returns:
            str: the status
        """
        status = (
            self.steps
            .filter(
                status__in=[
                    WorkflowRunStepStatus.PAUSED,
                    WorkflowRunStepStatus.FAILED,
                    WorkflowRunStepStatus.CANCELLED,
                ]
            )
            .annotate(
                priority=Case(
                    When(
                        status=WorkflowRunStepStatus.PAUSED,
                        then=Value(1),
                    ),
                    When(
                        status=WorkflowRunStepStatus.FAILED,
                        then=Value(2),
                    ),
                    When(
                        status=WorkflowRunStepStatus.CANCELLED,
                        then=Value(3),
                    ),
                    output_field=IntegerField(),
                )
            )
            .order_by("priority")
            .values_list("status", flat=True)
            .first()
        )

        return status or WorkflowRunStepStatus.COMPLETED
