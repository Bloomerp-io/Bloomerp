from langchain_core.tools import tool, StructuredTool, BaseTool
from bloomerp.utils.sql import SqlQueryExecutor
from bloomerp.models import ApplicationField, AbstractBloomerpUser, Link
    

class BaseBloomerpTool(BaseTool):
    requires_user : bool = False # Tool that requires user id
    user : AbstractBloomerpUser = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = kwargs.get('user', None)

    


class GetDatabaseTablesTool(BaseBloomerpTool):
    description : str = '''
                    Function that returns a dictionary of tables and their columns in a database
                    Can be used to get to know the structure of the database for further querying
                    Function should only be called once during every conversation.
                    Tables that are not accessible to the user will not be returned.
                    '''
    name : str = "get_accessible_database_tables"


    def _run(self) -> list[tuple[str, list[str]]]:
        tables = ApplicationField.get_db_tables_and_columns(self.user)
        if not tables:
            return "User does not have access to any tables"
        else:
            return tables
    

class PerformSqlQueryTool(BaseBloomerpTool):
    description : str = '''Function that performs an SQL query and returns the result.
                    Can only be used to perform SELECT queries.'''
    name : str = "perform_sql_query"

    def _run(self, query: str) -> list[list[str]]:
        sql_executor = SqlQueryExecutor()
        try:
            result = sql_executor.execute_raw(query)
            return result
        except Exception as e:
            return [[str(e)]]
    
class GetApplicationRoutesTool(BaseBloomerpTool):
    description : str = '''Function that returns the list of application routes that are accessible to the user.
    Args:
        key_word : list[str] - A list of keywords to filter the routes
    '''
    name : str = "get_application_routes"

    def _run(self, key_words: list[str]) -> list[str]:
        links = []

        qs = Link.objects.none()
        for key_word in key_words:
            qs = qs | Link.objects.filter(name__icontains=key_word)

        qs = qs.distinct()

        for link in qs:
            if not link.requires_args():
                links.append(link.to_absolute_url())

        return links
            


        


BLOOMAI_TOOLS = [PerformSqlQueryTool, GetDatabaseTablesTool, GetApplicationRoutesTool]  # List of tools that can be used in the bloomai