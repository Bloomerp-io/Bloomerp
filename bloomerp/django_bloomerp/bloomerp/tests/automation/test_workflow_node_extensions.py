from django.core.exceptions import ValidationError
from django.test import TestCase

from bloomerp.automation import (
    BaseExecutor,
    WORKFLOW_NODE_REGISTRY,
    RouteResult,
    WorkflowIOSchema,
    WorkflowNodeDefinition,
    WorkflowNodeOutputPort,
)
from bloomerp.automation.run import load_step_output, run_workflow
from bloomerp.automation.workflow_state import WorkflowRunState
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_run_step import WorkflowRunStepStatus
from bloomerp.serializers.workflow import WorkflowSerializer


class DynamicBranchExecutor(BaseExecutor):
    @classmethod
    def get_output_ports(cls, config=None):
        return tuple(
            WorkflowNodeOutputPort(
                branch["id"],
                branch.get("label", branch["id"]),
                branch.get("max_connections", 1),
            )
            for branch in (config or {}).get("branches", [])
        )

    @classmethod
    def get_output_schema(cls, config=None, input_schema=None, port_id="default"):
        return WorkflowIOSchema(value_type="object", label=f"Output: {port_id}")

    def execute(self, input_data):
        return RouteResult(
            port_id=self.config["selected_port"],
            output=input_data,
        )


class RecordingSinkExecutor(BaseExecutor):
    calls = []

    def execute(self, input_data):
        self.calls.append(self.config["name"])
        return input_data


class TestWorkflowNodeExtensions(TestCase):
    dynamic_node_id = "TEST_DYNAMIC_BRANCH"
    sink_node_id = "TEST_RECORDING_SINK"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        WORKFLOW_NODE_REGISTRY.register(
            cls.dynamic_node_id,
            WorkflowNodeDefinition(
                cls.dynamic_node_id,
                "FLOW",
                "Test dynamic branch",
                "A test-only node with configuration-driven ports.",
                DynamicBranchExecutor,
            ),
        )
        WORKFLOW_NODE_REGISTRY.register(
            cls.sink_node_id,
            WorkflowNodeDefinition(
                cls.sink_node_id,
                "ACTION",
                "Test recording sink",
                "A test-only terminal node.",
                RecordingSinkExecutor,
            ),
        )
        cls.sub_type_field = WorkflowNode._meta.get_field("sub_type")
        cls.original_sub_type_choices = cls.sub_type_field.choices
        cls.sub_type_field.choices = [
            *cls.original_sub_type_choices,
            (cls.dynamic_node_id, "Test dynamic branch"),
            (cls.sink_node_id, "Test recording sink"),
        ]

    @classmethod
    def tearDownClass(cls):
        cls.sub_type_field.choices = cls.original_sub_type_choices
        WORKFLOW_NODE_REGISTRY.unregister(cls.dynamic_node_id)
        WORKFLOW_NODE_REGISTRY.unregister(cls.sink_node_id)
        super().tearDownClass()

    def setUp(self):
        RecordingSinkExecutor.calls = []
        self.workflow = Workflow.objects.create(
            name="Extension API test",
            enable_logging=True,
        )
        self.trigger = WorkflowNode.objects.create(
            workflow=self.workflow,
            type="TRIGGER",
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {}},
        )

    def _add_dynamic_branch(self, selected_port="approved"):
        return WorkflowNode.objects.create(
            workflow=self.workflow,
            type="FLOW",
            sub_type=self.dynamic_node_id,
            parameters={
                "selected_port": selected_port,
                "branches": [
                    {"id": "approved", "label": "Approved"},
                    {"id": "rejected", "label": "Rejected"},
                ],
            },
        )

    def _add_sink(self, name):
        return WorkflowNode.objects.create(
            workflow=self.workflow,
            type="ACTION",
            sub_type=self.sink_node_id,
            parameters={"name": name},
        )

    def test_undeclared_ports_receive_an_unlimited_default_port(self):
        ports = RecordingSinkExecutor.get_output_ports({})

        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0].id, "default")
        self.assertIsNone(ports[0].max_connections)

    def test_configuration_can_define_output_ports_and_port_specific_schemas(self):
        branch = self._add_dynamic_branch()

        self.assertEqual(
            [port.id for port in branch.get_output_ports()],
            ["approved", "rejected"],
        )
        schema = DynamicBranchExecutor.get_output_schema(
            branch.parameters,
            WorkflowIOSchema(value_type="object"),
            port_id="rejected",
        )
        self.assertEqual(schema.label, "Output: rejected")

    def test_route_result_executes_only_edges_on_the_selected_port(self):
        branch = self._add_dynamic_branch(selected_port="rejected")
        approved = self._add_sink("approved")
        rejected = self._add_sink("rejected")
        self.workflow.connect_nodes(self.trigger, branch)
        self.workflow.connect_nodes(branch, approved, output_port="approved")
        self.workflow.connect_nodes(branch, rejected, output_port="rejected")

        run_workflow(self.workflow, {"value": 42})

        self.assertEqual(RecordingSinkExecutor.calls, ["rejected"])

    def test_declared_port_connection_limit_is_enforced_by_the_model(self):
        branch = self._add_dynamic_branch()
        self.workflow.connect_nodes(
            branch,
            self._add_sink("first"),
            output_port="approved",
        )

        with self.assertRaises(ValidationError):
            self.workflow.connect_nodes(
                branch,
                self._add_sink("second"),
                output_port="approved",
            )

    def test_unknown_output_port_is_rejected_by_the_model(self):
        branch = self._add_dynamic_branch()

        with self.assertRaises(ValidationError):
            self.workflow.connect_nodes(
                branch,
                self._add_sink("sink"),
                output_port="missing",
            )

    def test_serializer_exposes_dynamic_ports_and_persists_edge_port(self):
        branch = self._add_dynamic_branch()
        sink = self._add_sink("sink")
        self.workflow.connect_nodes(branch, sink, output_port="rejected")

        payload = WorkflowSerializer(self.workflow).data

        serialized_branch = next(
            node for node in payload["nodes"] if node["id"] == branch.id
        )
        serialized_edge = next(
            edge for edge in payload["edges"] if edge["from_node"] == f"node-{branch.id}"
        )
        self.assertEqual(
            [port["id"] for port in serialized_branch["output_ports"]],
            ["approved", "rejected"],
        )
        self.assertEqual(serialized_edge["output_port"], "rejected")

    def test_serializer_rejects_too_many_connections_for_a_port(self):
        branch = self._add_dynamic_branch()
        first = self._add_sink("first")
        second = self._add_sink("second")
        payload = WorkflowSerializer(self.workflow).data
        payload["edges"] = [
            {
                "from_node": f"node-{branch.id}",
                "to_node": f"node-{first.id}",
                "output_port": "approved",
            },
            {
                "from_node": f"node-{branch.id}",
                "to_node": f"node-{second.id}",
                "output_port": "approved",
            },
        ]

        serializer = WorkflowSerializer(self.workflow, data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("connection limit", str(serializer.errors))

    def test_workflow_run_model_creates_a_step_with_serialized_output_and_state(self):
        workflow_run = WorkflowRun.objects.create(workflow=self.workflow)
        state = WorkflowRunState(
            workflow_id=self.workflow.id,
            workflow_run_id=workflow_run.id,
        )
        output = RouteResult(port_id="default", output={"value": 42})

        step = workflow_run.create_step(
            node=self.trigger,
            sequence=0,
            status=WorkflowRunStepStatus.COMPLETED,
            state=state,
            enabled=True,
            output_data=output,
        )

        self.assertEqual(step.state["current_step_id"], step.id)
        self.assertEqual(load_step_output(step), output)
