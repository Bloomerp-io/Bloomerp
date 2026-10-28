from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.model_fields.code_field import CodeField
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)
from bloomerp.utils.sql import SqlQueryExecutor


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
        )
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
