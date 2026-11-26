from urllib.parse import urlencode

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.model_fields.code_field import CodeField
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    get_default_object_actions,
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectActionContext,
    ObjectModalAction,
)
from bloomerp.utils.sql import SqlQueryExecutor


def _can_apply_query(context: ObjectActionContext) -> bool:
    """Offer Apply to users allowed to execute SQL and read this query's SQL field."""
    from bloomerp.permissions.definition import BloomerpPermission
    from bloomerp.permissions.manager import UserPolicyManager

    user = context.request.user
    return user.has_perm("bloomerp.execute_sql_query") and UserPolicyManager(
        user
    ).has_access_to_object(context.object, BloomerpPermission.VIEW, fields=["query"])


class SqlQuery(BloomerpModel):
    """
    A model to store SQL queries that can be used in Widgets
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'sql_query'
        verbose_name = _('SQL Query')
        verbose_name_plural = _('SQL Queries')
        permissions = [
            ('execute_sql_query', 'Can execute SQL queries')
            # Maybe add more permissions here corresponding to the actions that can be performed on the query
        ]
    
    bloomerp_config = BloomerpModelConfig(
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("SQL queries"),
                    display_fields=["name", "datetime_updated"],
                    sort_field="name",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=1,
                            title=gettext_noop("Query"),
                            items=[LayoutItem(id="name"), LayoutItem(id="query")],
                        )
                    ]
                )
            ]
        ),
        api_settings=ApiSettings(
            enable_auto_generation=True,
        ),
        object_actions=lambda model: [
            *get_default_object_actions(model),
            ObjectModalAction(
                id="apply_query",
                label=gettext_noop("Apply query"),
                endpoint=lambda context: f"{reverse('components_execute_sql_query')}?{urlencode({'query_id': str(context.object.pk)})}",
                should_render_func=_can_apply_query,
                icon="fa-solid fa-play",
                size="xl",
            )
        ]
    )
    
    
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    query = CodeField(language='sql', help_text=_("SQL Query to execute"), verbose_name=_("Query"))

    # String fields
    search_fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize the query executor
        if self.pk is not None:
            self.executor = SqlQueryExecutor(
                cache_time=60,
                cache_id= str(self.pk) + self.name 
            )
        else:
            self.executor = SqlQueryExecutor()
    
    def is_safe(self):
        '''
        Check if the query is a SELECT statement
        '''
        return self.executor.is_safe(self.query)
    
    def __str__(self):
        return self.name
