from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueField, WorkflowValueType
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.widgets.code_editor_widget import CodeEditorWidget


class SqlQueryForm(BaseWorkflowNodeForm):
    query = forms.CharField(
        widget=CodeEditorWidget(language='sql'), 
        label="SQL Query"
    )
    page_size = forms.IntegerField(
        label="Page Size",
        required=False,
        help_text="Optional: Limit the number of rows returned by the query.",
        initial=100
    )
    
    
    
class SqlQueryActionExecutor(BaseExecutor):
    config_form = SqlQueryForm

    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="SQL Query Result",
            description="The result of the executed SQL query.",
            fields=[
                WorkflowValueField(
                    path="result",
                    value_type=WorkflowValueType.LIST,
                    label="Result",
                    description="The list of results from the SQL query.",
                    optional=True,
                    children=[
                        WorkflowValueField(
                            path="result.0",
                            value_type=WorkflowValueType.OBJECT,
                            label="Row",
                            description="A single row from the SQL query result.",
                            optional=True,
                        )
                    ]
                ),
                WorkflowValueField(
                    path="status",
                    value_type=WorkflowValueType.STRING,
                    label="Status",
                    description="The status of the SQL query execution (e.g., success, error).",
                    optional=False,
                ),
                WorkflowValueField(
                    path="error_message",
                    value_type=WorkflowValueType.STRING,
                    label="Error Message",
                    description="The error message if the SQL query execution failed.",
                    optional=True,
                ),
                WorkflowValueField(
                    path="count",
                    value_type=WorkflowValueType.NUMBER,
                    label="Row Count",
                    description="The number of rows returned by the SQL query.",
                    optional=True,
                ),
                WorkflowValueField(
                    path="query",
                    value_type=WorkflowValueType.STRING,
                    label="Executed Query",
                    description="The SQL query that was executed.",
                    optional=False,
                ),
                WorkflowValueField(
                    path="execution_time",
                    value_type=WorkflowValueType.NUMBER,
                    label="Execution Time (ms)",
                    description="The time taken to execute the SQL query in milliseconds.",
                    optional=True,
                ),
                WorkflowValueField(
                    path="columns",
                    value_type=WorkflowValueType.LIST,
                    label="Columns",
                    description="The list of column names returned by the SQL query.",
                    optional=True,
                )
            ]
        )
    
    def execute(self, trigger_data):
        params = self.resolve_config(trigger_data)
        
        # Get the parameters
        sql_query = params['query']
        page_size = params.get('page_size')
        if page_size:
            extra_args = {"page_size": page_size}
        else:
            extra_args = {}
        
        executor = SqlExecutor()
        try:
            response = executor.execute_query(sql_query, **extra_args)
            return {
                "status": "success",
                "error_message": "",
                "result": response.rows,
                "count": response.row_count,
                "query": sql_query,
                "execution_time": response.execution_ms,
                "columns": response.columns
            }
        except Exception as e:
            return {
                "status": "error",
                "error_message": str(e),
                "result": [],
                "count": 0,
                "query": sql_query,
                "execution_time": 0,
                "columns": []
            }
        
