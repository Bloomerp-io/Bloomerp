from dataclasses import dataclass, field
from typing import Any, Callable

from django.test import TestCase, modify_settings

from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY, WorkflowNodeDefinition
from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema
from bloomerp.management.commands import save_application_fields
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.utils.json_serialization import make_json_safe


EXPECTED_OUTPUT_UNSET = object()


@dataclass
class WorkflowNodeSimulation:
    """One direct execution scenario for a registered workflow node."""

    name: str | None = None
    parameters: dict = field(default_factory=dict)
    trigger_data: Any = field(default_factory=dict)
    expected_output: Any = EXPECTED_OUTPUT_UNSET
    output_validators: Callable[[Any], bool] | list[Callable[[Any], bool]] | None = None
    expected_exception: type[Exception] | tuple[type[Exception], ...] | None = None
    expected_exception_message: str | None = None
    input_schema: WorkflowIOSchema | None = None
    expected_output_schema: Any = EXPECTED_OUTPUT_UNSET
    output_schema_validators: (
        Callable[[WorkflowIOSchema], bool]
        | list[Callable[[WorkflowIOSchema], bool]]
        | None
    ) = None


@modify_settings(INSTALLED_APPS={'remove': 'bloomerp_modules'})
class BloomerpWorkflowNodeTestCase(TestCase):
    """Base class for registration and execution tests of a workflow node."""

    node_id: str | None = None
    executor_class: type[BaseExecutor] | None = None
    workflow: Workflow | None = None


    def setUp(self):
        save_application_fields.Command().handle(suppress_output=True)
        
        return super().setUp()
    
    def create_test_workflow(self) -> Workflow:
        """Create the workflow used by node simulations. Overridable"""
        return Workflow.objects.create(name="Test Workflow")


    def get_test_workflow(self) -> Workflow:
        """Returns the test workflow for this test case class

        Returns:
            Workflow: _description_
        """
        if self.workflow is not None:
            return self.workflow
        self.workflow = self.create_test_workflow()
        return self.workflow

    def _assert_validators(
        self,
        value: Any,
        validators: Callable[[Any], bool] | list[Callable[[Any], bool]] | None,
        *,
        subject: str,
    ) -> None:
        if validators is None:
            return

        validator_list = validators if isinstance(validators, list) else [validators]
        for validator in validator_list:
            self.assertTrue(
                validator(value),
                f"{subject} validator {getattr(validator, '__name__', repr(validator))} failed.",
            )


    def get_node_definition(self, node_id: str | None = None) -> WorkflowNodeDefinition:
        """Return a registered node definition or fail with a useful message."""
        selected_node_id = node_id or self.node_id
        definition = WORKFLOW_NODE_REGISTRY.get(selected_node_id)
        if definition is None:
            raise AssertionError(f"Workflow node {selected_node_id!r} is not registered")
        return definition

    def add_node(
        self,
        node_id: str | None = None,
        *,
        parameters: dict | None = None,
        workflow: Workflow | None = None,
    ) -> WorkflowNode:
        """Add a registered node to the current simulation workflow."""
        definition = self.get_node_definition(node_id)
        selected_workflow = workflow or self.workflow
        return WorkflowNode.objects.create(
            workflow=selected_workflow,
            type=definition.type,
            sub_type=definition.id,
            parameters=make_json_safe(parameters or {}),
        )

    def add_trigger(self, **kwargs) -> WorkflowNode:
        """Add the configured node and assert that it is a trigger."""
        definition = self.get_node_definition()
        if definition.type != "TRIGGER":
            raise AssertionError(f"Workflow node {definition.id!r} is not a trigger")
        return self.add_node(**kwargs)

    def get_simulations(self) -> list[WorkflowNodeSimulation]:
        """Return direct execution scenarios for the configured node."""
        return []

    def test_workflow_node_simulations(self) -> None:
        """
        Use case: A registered workflow node declares execution simulations.
        Expected result: The node exists, can be persisted, and produces valid output.
        """
        # 1. Do not execute the reusable base class itself.
        if self.node_id is None:
            return

        # 2. Create the shared workflow before subclasses build simulations.
        definition = self.get_node_definition()
        if self.executor_class is not None:
            self.assertIs(definition.executor_cls, self.executor_class)
        self.workflow = self.create_test_workflow()

        # 3. Execute the configured node once for every simulation.
        for index, simulation in enumerate(self.get_simulations(), start=1):
            with self.subTest(name=simulation.name or f"simulation {index}"):
                node = self.add_node(
                    self.node_id,
                    parameters=simulation.parameters,
                )
                if simulation.expected_exception is not None:
                    if simulation.expected_output is not EXPECTED_OUTPUT_UNSET:
                        self.fail(
                            "A simulation cannot declare both expected_output and "
                            "expected_exception."
                        )
                    if simulation.expected_exception_message is None:
                        exception_assertion = self.assertRaises(
                            simulation.expected_exception
                        )
                    else:
                        exception_assertion = self.assertRaisesRegex(
                            simulation.expected_exception,
                            simulation.expected_exception_message,
                        )
                    with exception_assertion:
                        node.execute(simulation.trigger_data)
                else:
                    output = node.execute(simulation.trigger_data)
                    if simulation.expected_output is not EXPECTED_OUTPUT_UNSET:
                        self.assertEqual(output, simulation.expected_output)
                    self._assert_validators(
                        output,
                        simulation.output_validators,
                        subject="Output",
                    )

                if (
                    simulation.expected_output_schema is not EXPECTED_OUTPUT_UNSET
                    or simulation.output_schema_validators is not None
                ):
                    output_schema = definition.executor_cls.get_output_schema(
                        simulation.parameters,
                        simulation.input_schema,
                    )
                    if simulation.expected_output_schema is not EXPECTED_OUTPUT_UNSET:
                        self.assertEqual(output_schema, simulation.expected_output_schema)
                    self._assert_validators(
                        output_schema,
                        simulation.output_schema_validators,
                        subject="Output schema",
                    )
