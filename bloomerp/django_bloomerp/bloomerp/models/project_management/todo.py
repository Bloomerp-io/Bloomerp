from django.db import connection, models
from django.http import HttpRequest, HttpResponse
from slugify import slugify
from bloomerp.model_fields.text_editor_field import TextEditorField
from bloomerp.model_fields.user_field import UserField
from bloomerp.models import BloomerpModel
from django.conf import settings
from django.utils.translation import gettext_lazy as _, gettext_noop
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError

from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import (
    BloomerpModelConfig,
    KanbanDataView,
    ModelViewSettings,
    ObjectAction,
    ObjectHTML,
    TableDataView,
)
from bloomerp.utils.models import get_list_view_url
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileFilter, FieldConfig
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.utils.requests import render_message
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.form_tile import render
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileType


class TodoPriority(models.TextChoices):
    URGENT = ('urgent', _('Urgent'))
    HIGH = ('high', _('High'))
    MEDIUM = ('medium', _('Medium'))
    LOW = ('low', _('Low'))
    
# TODO: Create effort model based on t-shirt sizing (check linear for this)
class TodoEffort(models.IntegerChoices):
    XS = (1, _('XS'))
    S = (2, _('S'))
    M = (4, _('M'))
    L = (8, _('L'))
    XL = (16, _('XL'))

# TODO: Status should be based on what is defined in the overall bloomerp settings module
# TODO: Use status field for this one -> status field can be used later on in table views 
class TodoStatus(models.TextChoices):
    BACKLOG = ('backlog', _('Backlog'))
    IN_PROGRESS = ('in_progress', _('In Progress'))
    IN_REVIEW = ('in_review', _('In Review'))
    COMPLETED = ('completed', _('Completed'))
    CANCELLED = ('cancelled', _('Cancelled'))
    DUPLICATE = ('duplicate', _('Duplicate'))


def _average_completion_speed_query() -> str:
    if connection.vendor == "sqlite":
        duration_expression = (
            "julianday(datetime_completed) - julianday(datetime_created)"
        )
    else:
        duration_expression = (
            "EXTRACT(EPOCH FROM (datetime_completed - datetime_created)) / 86400.0"
        )

    return f"""
        SELECT {duration_expression} AS completion_days
        FROM bloomerp_todo
        WHERE datetime_completed IS NOT NULL
    """


def _mark_as_completed(request:HttpRequest, object:"Todo") -> HttpResponse:
    """
    Marks the todo as completed and sets the datetime_completed field to the current time.
    """
    from bloomerp.permissions.manager import UserPermissionManager
    manager = UserPermissionManager(request.user)
    
    if not manager.has_access_to_object(object, BloomerpPermission.CHANGE):
        message = _("You do not have permission to mark this todo as completed.")
    else:
        message = _("Todo marked as completed.")
        object.status = TodoStatus.COMPLETED
        object.save()
    
    return render_message(request, message, "info")
    

class Todo(BloomerpModel):
    """
    The todo model is for Bloomerp's internal project management module.
    """
    bloomerp_config = BloomerpModelConfig(
        module="todos_and_initiatives",
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    title=gettext_noop("Details"),
                    columns=4,
                    items=[
                        LayoutItem(id="title", colspan=3),
                        LayoutItem(id="status", colspan=1),
                        LayoutItem(id="priority", colspan=1),
                        LayoutItem(id="effort", colspan=1),
                        LayoutItem(id="labels", colspan=1),
                        LayoutItem(id="initiative", colspan=1),
                        LayoutItem(id="content", colspan=4),
                    ],
                ),
                LayoutRow(
                    title=gettext_noop("Users"),
                    columns=4,
                    items=[
                        LayoutItem(id="requested_by"),
                        LayoutItem(id="assigned_to"),
                    ],
                ),
                LayoutRow(
                    title=gettext_noop("Timeline"),
                    columns=4,
                    items=[
                        LayoutItem(id="required_by"),
                        LayoutItem(id="datetime_completed"),
                        LayoutItem(id="is_completed"),
                    ],
                ),
            ]
        ),
        string_search_fields=["title", "content"],
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                KanbanDataView(
                    name="Todo workflow",
                    display_fields=[
                        "title",
                        "priority",
                        "effort",
                        "assigned_to",
                        "required_by",
                    ],
                    group_by_field="status",
                    sort_field="priority",
                ),
                TableDataView(
                    name="All todos",
                    is_default=False,
                    display_fields=[
                        "title",
                        "status",
                        "priority",
                        "assigned_to",
                        "initiative",
                        "required_by",
                    ],
                    sort_field="required_by",
                ),
            ]
        ),
        object_actions=[
            ObjectHTML(
                template_name="models/todo/copy_git_branch_name.html"
            ),
            ObjectAction(
                id="mark_as_completed",
                label=gettext_noop("Mark as Completed"),
                should_render_func=lambda _, object: object.status != TodoStatus.COMPLETED,
                execution_func=_mark_as_completed
            )
        ],
        tiles=[
            AnalyticsTileConfig(
                type=AnalyticsTileType.KPI.value.key,
                id="todos:number_of_todos",
                name="Number of todos",
                description="Total number of visible todos.",
                query="SELECT * FROM bloomerp_todo",
                icon="fa-solid fa-list-check",
                fields={
                    "value": [
                        FieldConfig(
                            name="id",
                            opts={
                                "aggregator": "COUNT",
                                "formatter": "INTEGER",
                            },
                        )
                    ]
                },
                filters=[
                    AnalyticsTileFilter(
                        field="status",
                        type="text",
                    )
                ]
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.KPI.value.key,
                id="todos:open_todos",
                name="Open todos",
                description="Todos that still require action.",
                query="""
                    SELECT COUNT(*) AS open_count
                    FROM bloomerp_todo
                    WHERE status NOT IN ('completed', 'cancelled', 'duplicate')
                """,
                icon="fa-solid fa-hourglass-half",
                fields={
                    "value": [
                        FieldConfig(
                            name="open_count",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "INTEGER",
                            },
                        )
                    ]
                },
                opts={
                    "advanced_formatting_value" : """<a href='{% url 'todos_model' %}?status'>{{ var_open_count }}</a>"""
                }
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.KPI.value.key,
                id="todos:completion_rate",
                name="Completion rate",
                description="Share of visible todos marked as completed.",
                query="""
                    SELECT COALESCE(
                        1.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0),
                        0
                    ) AS completion_rate
                    FROM bloomerp_todo
                """,
                icon="fa-solid fa-circle-check",
                fields={
                    "value": [
                        FieldConfig(
                            name="completion_rate",
                            opts={
                                "aggregator": "FIRST",
                                "formatter": "PERCENTAGE",
                            },
                        )
                    ]
                },
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.KPI.value.key,
                id="todos:average_completion_speed",
                name="Average completion speed",
                description="Average elapsed time for completed todos.",
                query=_average_completion_speed_query(),
                icon="fa-solid fa-stopwatch",
                fields={
                    "value": [
                        FieldConfig(
                            name="completion_days",
                            opts={
                                "aggregator": "AVG",
                                "formatter": "DOUBLE_US",
                                "suffix": " days",
                            },
                        )
                    ]
                },
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.PIE_CHART.value.key,
                id="todos:status_distribution",
                name="Todos by status",
                description="Distribution of visible todos across workflow states.",
                query="""
                    SELECT
                        CASE status
                            WHEN 'backlog' THEN 'Backlog'
                            WHEN 'in_progress' THEN 'In progress'
                            WHEN 'in_review' THEN 'In review'
                            WHEN 'completed' THEN 'Completed'
                            WHEN 'cancelled' THEN 'Cancelled'
                            WHEN 'duplicate' THEN 'Duplicate'
                            ELSE status
                        END AS status_label,
                        1 AS todo_count
                    FROM bloomerp_todo
                """,
                icon="fa-solid fa-chart-pie",
                fields={
                    "labels": [FieldConfig(name="status_label")],
                    "values": [
                        FieldConfig(
                            name="todo_count",
                            opts={"label": "Todos", "formatter": "INTEGER"},
                        )
                    ],
                },
                opts={"legend_position": "right", "show_legend": True},
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.TWO_DIM_CHART.value.key,
                id="todos:priority_distribution",
                name="Todos by priority",
                description="Current workload grouped by priority.",
                query="""
                    SELECT
                        CASE priority
                            WHEN 'urgent' THEN 'Urgent'
                            WHEN 'high' THEN 'High'
                            WHEN 'medium' THEN 'Medium'
                            WHEN 'low' THEN 'Low'
                            ELSE priority
                        END AS priority_label,
                        1 AS todo_count
                    FROM bloomerp_todo
                """,
                icon="fa-solid fa-chart-column",
                fields={
                    "x_axis": [FieldConfig(name="priority_label")],
                    "y_axis": [
                        FieldConfig(
                            name="todo_count",
                            opts={"label": "Todos", "color": "#f59e0b"},
                        )
                    ],
                },
                opts={
                    "chart_type": "bar",
                    "x_axis_order": "Urgent,High,Medium,Low",
                    "show_legend": False,
                },
            ),
            AnalyticsTileConfig(
                type=AnalyticsTileType.TWO_DIM_CHART.value.key,
                id="todos:completion_trend",
                name="Todo completion trend",
                description="Completed todos grouped by completion date.",
                query="""
                    SELECT
                        CAST(datetime_completed AS DATE) AS completion_date,
                        1 AS completed_count
                    FROM bloomerp_todo
                    WHERE datetime_completed IS NOT NULL
                """,
                icon="fa-solid fa-chart-line",
                fields={
                    "x_axis": [FieldConfig(name="completion_date")],
                    "y_axis": [
                        FieldConfig(
                            name="completed_count",
                            opts={"label": "Completed", "color": "#10b981"},
                        )
                    ],
                },
                opts={
                    "chart_type": "line",
                    "x_axis_label": "Completion date",
                    "show_legend": False,
                },
            ),
        ]
    )

    class Meta(BloomerpModel.Meta):
        verbose_name = _("Todo")
        verbose_name_plural = _("Todos")
        managed = True
        db_table = 'bloomerp_todo'

    avatar = None
    allow_string_search = False # Do not allow string search for todos (we dont want to-do's to be searchable in the search bar)

    assigned_to = UserField(
        on_delete=models.CASCADE, 
        null=True,
        blank=True,
        related_name='todos',
        verbose_name=_("Assigned To"),
        help_text=_("The user to whom the todo is assigned")
        )
    requested_by = UserField( 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE, 
        related_name='requested_todos', 
        verbose_name=_("Requested By"),
        help_text=_("The user who requested the todo")
        )
    required_by = models.DateField(
        null=True, 
        blank=True,
        verbose_name=_("Required By"),
        help_text=_("The date by which the todo is required")
        )
    priority = models.CharField(
        max_length=20,
        help_text=_("The priority of the todo"), 
        choices=TodoPriority.choices,
        default=TodoPriority.MEDIUM,
        verbose_name=_("Priority")
        )
    effort = models.IntegerField(
        null=True, 
        blank=True,
        help_text=_("The effort required for the todo"),
        choices=TodoEffort.choices,
        default=TodoEffort.M,
        verbose_name=_("Effort")
        )
    title = models.CharField(
        max_length=255, 
        help_text=_("The name of the todo"),
        verbose_name=_("Title")
        )
    content = TextEditorField(
        blank=True, 
        null=True,
        verbose_name=_("Content")
        )
    datetime_completed = models.DateTimeField(
        null=True, 
        blank=True,
        editable=False,
        help_text=_("The date and time when the todo was completed"),
        verbose_name=_("Date Completed")
        )
    status = models.CharField(
        max_length=50, 
        choices=TodoStatus.choices,
        default=TodoStatus.BACKLOG,
        verbose_name=_("Status")
        )
    labels = models.ManyToManyField(
        'bloomerp.TodoLabel',
        blank=True,
        help_text=_("Labels assigned to the todo"),
        verbose_name=_("Labels")
        )
    initiative = models.ForeignKey(
        'bloomerp.Initiative',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='todos',
        help_text=_("The initiative this todo belongs to"),
        verbose_name=_("Initiative")
        )

    # For if the todo is related to a model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Content Type"),
        help_text=_("The content type of the related object"),
    )
    object_id = models.CharField(
        max_length=36,
        null=True,
        blank=True,
        help_text=_("The ID of the related object"),
        verbose_name=_("Object ID"),
    ) # In order to support both UUID and integer primary keys
    content_object = GenericForeignKey(
        "content_type", 
        "object_id"
    )

    @property
    def content_safe(self):
        from django.utils.safestring import mark_safe
        return mark_safe(self.content)

    @property
    def is_completed(self) -> bool:
        """Returns whether the item has been completed or not

        Returns:
            bool: _description_
        """
        return self.status == TodoStatus.COMPLETED
    
    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        from django.utils import timezone
        from django.core.exceptions import ObjectDoesNotExist

        # Set the datetime completed to None if the todo is not completed
        if self.is_completed and not self.datetime_completed:
            self.datetime_completed = timezone.now()
        elif not self.is_completed:
            self.datetime_completed = None


        if self.content_type and self.object_id:
            try:
                self.content_object  # Triggers a lookup
            except ObjectDoesNotExist:
                errors['content_object'] = _("The related object does not exist")

        if errors:
            raise ValidationError(errors)

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()  # This will call the clean method and raise a ValidationError if there are any validation errors
        super().save(*args, **kwargs)

    
    @property
    def git_branch_name(self) -> str:
        """Returns a git branch name based on the todo title and id

        Returns:
            str: the git branch name
        """
        if not self.id:
            return ""
        
        return f"todo/{str(self.id)[-4:]}-{slugify(self.title)}"
