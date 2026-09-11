from unittest.mock import patch

from bloomerp.automation.actions.run_workflow import RunWorkflowExecutor, RunWorkflowForm
from bloomerp.automation.base_executor import NodeExecutionError
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueType
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.automation.run import run_workflow
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeScenario,
)


class TestRunWorkflowNode(BloomerpWorkflowNodeTestCase):
    node_id = "RUN_WORKFLOW"
    executor_class = RunWorkflowExecutor

    def test_config_form_accepts_a_workflow_id(self):
        target = self._create_workflow_with_trigger("Selected workflow")
        form = RunWorkflowForm(
            data={"workflow_id": target.id, "execution": "SYNC"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["workflow_id"], target.id)

    def _create_workflow_with_trigger(
        self,
        name: str,
        *,
        run_asynchronously: bool = False,
    ) -> Workflow:
        workflow = Workflow.objects.create(
            name=name,
            run_asynchronously=run_asynchronously,
            enable_logging=True,
        )
        WorkflowNode.objects.create(
            name="Trigger",
            workflow=workflow,
            type="TRIGGER",
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {}},
        )
        return workflow

    def _add_call(
        self,
        source: Workflow,
        target: Workflow,
        *,
        execution: str = "USE_WORKFLOW",
    ) -> WorkflowNode:
        trigger = source.get_trigger()
        call = WorkflowNode.objects.create(
            name="Run child workflow",
            workflow=source,
            type="ACTION",
            sub_type=self.node_id,
            parameters={
                "workflow_id": target.id,
                "execution": execution,
            },
        )
        source.connect_nodes(trigger, call)
        return call

    def get_simulations(self) -> list[WorkflowNodeScenario]:
        target = self._create_workflow_with_trigger("Directly called workflow")
        input_schema = WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="Parent output",
        )
        return [
            WorkflowNodeScenario(
                name="passes input through and runs the selected workflow",
                parameters={"workflow_id": target.id, "execution": "SYNC"},
                trigger_data={"value": 42},
                expected_output={"value": 42},
                input_schema=input_schema,
                expected_output_schema=input_schema,
                output_validators=[
                    lambda output: output["value"] == 42,
                    lambda output: Workflow.objects.get(pk=target.pk).runs.count() == 1,
                ],
            )
        ]

    def test_use_workflow_execution_queues_an_asynchronous_child(self):
        parent = self._create_workflow_with_trigger("Parent")
        child = self._create_workflow_with_trigger(
            "Asynchronous child",
            run_asynchronously=True,
        )
        self._add_call(parent, child)

        with patch(
            "bloomerp.automation.run.run_workflow_async.delay"
        ) as delay:
            run_workflow(parent, {"value": 42})

        delay.assert_called_once()
        self.assertEqual(delay.call_args.args[0], child.id)
        self.assertEqual(child.runs.count(), 1)
        self.assertEqual(child.runs.get().status, "QUEUED")

    def test_force_sync_runs_an_asynchronous_child_inline(self):
        parent = self._create_workflow_with_trigger("Parent")
        child = self._create_workflow_with_trigger(
            "Normally asynchronous child",
            run_asynchronously=True,
        )
        self._add_call(parent, child, execution="SYNC")

        run_workflow(parent, {"value": 42})

        self.assertEqual(child.runs.count(), 1)

    def test_force_async_queues_a_synchronous_child(self):
        parent = self._create_workflow_with_trigger("Parent")
        child = self._create_workflow_with_trigger("Normally synchronous child")
        self._add_call(parent, child, execution="ASYNC")

        with patch(
            "bloomerp.automation.run.run_workflow_async.delay"
        ) as delay:
            run_workflow(parent, {"value": 42})

        delay.assert_called_once()
        self.assertEqual(delay.call_args.args[0], child.id)
        self.assertEqual(child.runs.count(), 1)
        self.assertEqual(child.runs.get().status, "QUEUED")

    def test_rejects_a_direct_self_call(self):
        workflow = self._create_workflow_with_trigger("Recursive workflow")
        self._add_call(workflow, workflow)

        with self.assertRaisesRegex(NodeExecutionError, "may not create a cycle"):
            run_workflow(workflow, {})

    def test_rejects_an_indirect_workflow_cycle(self):
        first = self._create_workflow_with_trigger("First")
        second = self._create_workflow_with_trigger("Second")
        self._add_call(first, second)
        self._add_call(second, first)

        with self.assertRaisesRegex(NodeExecutionError, "may not create a cycle"):
            run_workflow(first, {})
