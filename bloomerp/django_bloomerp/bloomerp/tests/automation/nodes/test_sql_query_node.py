from bloomerp.automation.actions.sql_query import SqlQueryActionExecutor
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeSimulation,
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

class TestSqlQueryNode(BloomerpWorkflowNodeTestCase):
    node_id = 'SQL_QUERY'
    executor_class = SqlQueryActionExecutor

    def get_simulations(self) -> list[WorkflowNodeSimulation]:
        Todo.objects.create(title="Title")
        Todo.objects.create(title="Another todo")

        return [
            WorkflowNodeSimulation(
                name="Normal SQL Query",
                parameters={
                    "query" : "SELECT * FROM bloomerp_todo"
                },
                output_validators=[
                    validate_keys,
                    lambda output: output.get("count") == 2,
                ]
            ),
            WorkflowNodeSimulation(
                name="Invalid SQL Query returns error",
                parameters={
                    "query" : "invalid sql query"
                },
                output_validators=[
                    validate_keys,
                    lambda output: output.get("status") == "error"
                ]
            ),
            WorkflowNodeSimulation(
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
