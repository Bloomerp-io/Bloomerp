from bloomerp.automation.actions.sql_query import SqlQueryActionExecutor
from bloomerp.automation.schema import WorkflowValueType
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeScenario,
)


def validate_keys(output:dict):
    return all(
        x in output for x in [
            "status",
            "error_message",
            "result",
            "count",
            "query",
            "execution_time",
            "columns"
        ]
    )


def validate_inferred_output_schema(schema):
    result_field = next(field for field in schema.fields if field.path == "result")
    row_field = next(field for field in result_field.children if field.path == "result.0")
    inferred_fields = {field.path: field.value_type for field in row_field.children}

    return inferred_fields == {
        "result.0.title": WorkflowValueType.UNKNOWN,
        "result.0.answer_count": WorkflowValueType.NUMBER,
        "result.0.is_active": WorkflowValueType.BOOLEAN,
        "result.0.report_date": WorkflowValueType.DATETIME,
        "result.0.status_label": WorkflowValueType.STRING,
    }


def validate_generic_output_schema(schema):
    result_field = next(field for field in schema.fields if field.path == "result")
    row_field = next(field for field in result_field.children if field.path == "result.0")
    return row_field.children == []

class TestSqlQueryNode(BloomerpWorkflowNodeTestCase):
    node_id = 'SQL_QUERY'
    executor_class = SqlQueryActionExecutor

    def get_simulations(self) -> list[WorkflowNodeScenario]:
        Todo.objects.create(title="Title")
        Todo.objects.create(title="Another todo")

        return [
            WorkflowNodeScenario(
                name="Normal SQL Query",
                parameters={
                    "query": """
                        SELECT
                            title,
                            42 AS answer_count,
                            TRUE AS is_active,
                            CAST('2026-09-10' AS DATE) AS report_date,
                            'ready' AS status_label
                        FROM bloomerp_todo
                    """,
                },
                output_validators=[
                    validate_keys,
                    lambda output: output.get("count") == 2,
                ],
                output_schema_validators=validate_inferred_output_schema,
            ),
            WorkflowNodeScenario(
                name="Invalid SQL Query returns error",
                parameters={
                    "query" : "invalid sql query"
                },
                output_validators=[
                    validate_keys,
                    lambda output: output.get("status") == "error"
                ],
                output_schema_validators=validate_generic_output_schema,
            ),
            WorkflowNodeScenario(
                name="Page parameter works",
                parameters={
                    "query" : "SELECT * FROM bloomerp_todo",
                    "page_size" : 1
                },
                output_validators=[
                    validate_keys,
                    lambda output: len(output.get("result", [])) == 1
                ]
            )
        ]
