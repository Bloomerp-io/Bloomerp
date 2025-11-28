from django.db import models
from django.core.exceptions import ValidationError
from bloomerp.models.base_bloomerp_model import BloomerpModel
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.fields import CodeField
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import AbsoluteUrlModelMixin
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from bloomerp.utils.sql import SqlQueryExecutor
from bloomerp.constants.widgets import WidgetType

class SqlQuery(BloomerpModel):
    """
    A model to store SQL queries that can be used in Widgets
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'sql_query'
        verbose_name = 'SQL Query'
        verbose_name_plural = 'SQL Queries'
        permissions = [
            ('execute_sql_query', 'Can execute SQL queries')
            # Maybe add more permissions here corresponding to the actions that can be performed on the query
        ]

    name = models.CharField(max_length=255)
    query = CodeField(language='sql', help_text=_("SQL Query to execute"))

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

    
    def result_dataframe(self):
        '''
        Execute the query and return the result
        '''
        return self.executor.execute_to_df(self.query)
    
    
    def result_dict(self):
        '''
        Execute the query and return the result
        '''
        return self.executor.execute_to_dict(self.query)
    
    
    def result_raw(self):
        '''
        Execute the query and return the result
        '''
        return self.executor.execute_raw(self.query)
    
    
    def result_value(self):
        '''
        Execute the query and return the result
        '''
        return self.executor.execute_to_first_value(self.query)


    def clean(self) -> None:
        '''
        Clean method does the following:
        - Check if the query is safe
        - Check if the query actually returns a result
        '''
        errors = {}

        # Check if the query is safe
        if not self.is_safe():
            errors['query'] = 'Unsafe query'

        # Check if the query returns a result
        result = self.executor.is_valid(self.query)
        if result != True:
            errors['query'] = result

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name


class Widget(BloomerpModel):
    """
    A widget represents a visual item that can be placed on a workspace.
    It takes in a query as entry point.
    """
    
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_widget'
    
    name = models.CharField(max_length=255, help_text=_("Name of the widget"))
    description = models.TextField(blank=True, null=True, help_text=_("Description of the widget"))
    query = models.ForeignKey(SqlQuery, on_delete=models.CASCADE, help_text=_("SQL query that represents the entry point for the widget"))
    widget_type = models.CharField(
        max_length=30,
        choices=[(wt.value, wt.name) for wt in WidgetType],
        help_text=_("Type of widget")
    )
    schema = models.JSONField()

    string_search_fields = ['name', 'description']

    def __str__(self):
        return self.name
    
    
class Workspace(AbsoluteUrlModelMixin, models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_workspace'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sub_module_id = models.CharField(max_length=255)
    module_id = models.CharField(max_length=255)
    
    
class WidgetOnWorkspace(models.Model):
    workspace = models.ForeignKey(to=Workspace, on_delete=models.CASCADE)
    widget = models.ForeignKey(to=Widget, on_delete=models.CASCADE)