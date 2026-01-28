from django.db import models
from django.core.exceptions import ValidationError
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.model_fields.code_field import CodeField
from django.utils.translation import gettext_lazy as _
from bloomerp.utils.sql import SqlQueryExecutor

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
