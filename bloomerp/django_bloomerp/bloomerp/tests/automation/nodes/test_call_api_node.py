from bloomerp.automation.actions.call_api import CallApiExecutor
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeSimulation,
)
from unittest.mock import Mock, patch


class TestCallApiNode(BloomerpWorkflowNodeTestCase):
    node_id = 'CALL_API'
    executor_class = CallApiExecutor

    def setUp(self) -> None:
        super().setUp()
        self.request_patch = patch(
            "bloomerp.automation.actions.call_api.requests.request",
            side_effect=self._request,
        )
        self.request_patch.start()
        self.addCleanup(self.request_patch.stop)

    @staticmethod
    def _request(_method, endpoint, **_kwargs):
        if endpoint == "https://api.example.test/todos/1":
            response = Mock(status_code=200)
            response.json.return_value = {"id": 1}
            return response
        raise ConnectionError("Unable to connect")

    def get_simulations(self) -> list[WorkflowNodeSimulation]:
        return [
            WorkflowNodeSimulation(
                name="Node returns a successful API response",
                parameters={
                    "method": "GET",
                    "endpoint": "https://api.example.test/todos/1",
                    "headers": {},
                    "payload": None,
                },
                expected_output={
                    "status": "success",
                    "status_code": 200,
                    "response": {"id": 1},
                },
            ),
            WorkflowNodeSimulation(
                name="Node returns an error when the API request fails",
                parameters={
                    "method": "GET",
                    "endpoint": "https://api.example.test/unavailable",
                    "headers": {},
                    "payload": None,
                },
                output_validators=lambda output: (
                    output.get("status") == "error"
                    and output.get("status_code") is None
                    and "Unable to connect" in output.get("response", "")
                ),
            ),
        ]
