"""Registry for BloomERP automation nodes."""

from dataclasses import dataclass
import json
from typing import Literal, Optional, Type

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext_lazy as _

from bloomerp.automation.actions.call_api import CallApiExecutor
from bloomerp.automation.actions.compute import ComputeExecutor
from bloomerp.automation.actions.create_object import CreateObjectExecutor
from bloomerp.automation.actions.delete_object import DeleteObjectExecutor
from bloomerp.automation.actions.enrich import EnrichExecutor
from bloomerp.automation.actions.extract_field import ExtractFieldExecutor
from bloomerp.automation.actions.generate_pdf import GeneratePdfExecutor
from bloomerp.automation.actions.get_object import GetObjectExecutor
from bloomerp.automation.actions.human_in_the_loop import HumanInTheLoopExecutor
from bloomerp.automation.actions.list_objects import ListObjectsExecutor
from bloomerp.automation.actions.merge_branches import MergeBranchExecutor
from bloomerp.automation.actions.run_workflow import RunWorkflowExecutor
from bloomerp.automation.actions.send_email import SendEmailExecutor
from bloomerp.automation.actions.send_user_message import SendUserMessage
from bloomerp.automation.actions.sql_query import SqlQueryActionExecutor
from bloomerp.automation.actions.update_object import UpdateObjectExecutor
from bloomerp.automation.actions.wait import WaitExecutor
from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.automation.flows.collect import CollectExecutor
from bloomerp.automation.flows.filter_objects import FilterObjectsExecutor
from bloomerp.automation.flows.for_each import ForEachExecutor
from bloomerp.automation.flows.if_condition import IfConditionExecutor
from bloomerp.automation.flows.object_if_condition import ObjectIfConditionExecutor
from bloomerp.automation.triggers.human_trigger import HumanTrigger
from bloomerp.automation.triggers.object_crud_trigger import ObjectCrudTrigger
from bloomerp.automation.triggers.on_schedule_trigger import ScheduleTrigger
from bloomerp.utils.registry import BaseRegistry


WorkflowNodeType = Literal["ACTION", "FLOW", "TRIGGER"]

WORKFLOW_NODE_TYPES: tuple[WorkflowNodeType, ...] = (
    "TRIGGER",
    "ACTION",
    "FLOW",
)

WORKFLOW_NODE_TYPE_METADATA = {
    "TRIGGER": {
        "name": _("Trigger"),
        "description": _("The trigger for a workflow"),
    },
    "ACTION": {
        "name": _("Action"),
        "description": _("An action to perform"),
    },
    "FLOW": {
        "name": _("Flow"),
        "description": _("A flow node to branch the workflow"),
    },
}


@dataclass(frozen=True)
class WorkflowNodeDefinition:
    id: str
    type: WorkflowNodeType
    name: str
    description: str
    executor_cls: Optional[Type[BaseExecutor]] = None
    icon: Optional[str] = None

    def get_output_ports(
        self,
        config: dict | None = None,
    ) -> tuple[WorkflowNodeOutputPort, ...]:
        if self.executor_cls is None:
            return ()
        return self.executor_cls.get_output_ports(config or {})

    @property
    def default_output_ports_json(self) -> str:
        return json.dumps(
            [port.to_dict() for port in self.get_output_ports({})],
            cls=DjangoJSONEncoder,
        )


class WorkflowNodeRegistry(BaseRegistry[WorkflowNodeDefinition]):
    def register(self, key: str, obj: WorkflowNodeDefinition) -> None:
        if obj.type not in WORKFLOW_NODE_TYPES:
            raise ValueError(f"Unsupported workflow node type {obj.type!r}")
        if any(definition.id == obj.id for definition in self.values()):
            raise ValueError(f"Workflow node ID {obj.id!r} is already registered")
        super().register(key, obj)

    def get(self, key: str) -> WorkflowNodeDefinition | None:
        registered = super().get(key)
        if registered is not None:
            return registered
        return next(
            (definition for definition in self.values() if definition.id == key),
            None,
        )

    def choices(self) -> list[tuple[str, str]]:
        return [(definition.id, definition.name) for definition in self.values()]

    def for_type(self, node_type: WorkflowNodeType) -> list[WorkflowNodeDefinition]:
        return [
            definition
            for definition in self.values()
            if definition.type == node_type
        ]

    def grouped(self, *, exclude_types: set[str] | None = None) -> list[dict]:
        excluded = exclude_types or set()
        return [
            {
                "id": node_type,
                **WORKFLOW_NODE_TYPE_METADATA[node_type],
                "nodes": self.for_type(node_type),
            }
            for node_type in WORKFLOW_NODE_TYPES
            if node_type not in excluded
        ]


WORKFLOW_NODE_REGISTRY = WorkflowNodeRegistry(WorkflowNodeDefinition)


WORKFLOW_NODES = [
    WorkflowNodeDefinition("ON_OBJECT_CREATE", "TRIGGER", "On Object Create", "Triggered when a new object is created", ObjectCrudTrigger, "fa-solid fa-circle-plus"),
    WorkflowNodeDefinition("ON_OBJECT_UPDATE", "TRIGGER", "On Object Update", "Triggered when an object is updated", ObjectCrudTrigger, "fa-solid fa-pen-to-square"),
    WorkflowNodeDefinition("ON_OBJECT_CREATE_OR_UPDATE", "TRIGGER", "On Object Create or Update", "Triggered when an object is created or updated", ObjectCrudTrigger, "fa-solid fa-arrows-rotate"),
    WorkflowNodeDefinition("ON_OBJECT_DELETE", "TRIGGER", "On Object Deletion", "Triggered when an object is deleted", ObjectCrudTrigger, "fa-solid fa-trash-can"),
    WorkflowNodeDefinition("SCHEDULE", "TRIGGER", "On Schedule", "Triggered on a defined schedule", ScheduleTrigger, "fa-solid fa-clock"),
    WorkflowNodeDefinition("HUMAN_TRIGGER", "TRIGGER", "Human Trigger", "Triggered by a human. Used for testing purposes.", HumanTrigger, "fa-solid fa-hand-pointer"),
    WorkflowNodeDefinition("SEND_EMAIL", "ACTION", "Send Email", "Sends an email to specified recipients", SendEmailExecutor, "fa-solid fa-envelope"),
    WorkflowNodeDefinition("GET_OBJECT", "ACTION", "Get Object", "Get a specific object by ID", GetObjectExecutor, "fa-solid fa-database"),
    WorkflowNodeDefinition("CREATE_OBJECT", "ACTION", "Create Object", "Creates a new object in the database", CreateObjectExecutor, "fa-solid fa-database"),
    WorkflowNodeDefinition("UPDATE_OBJECT", "ACTION", "Update Object", "Updates an existing object in the database", UpdateObjectExecutor, "fa-solid fa-pen"),
    WorkflowNodeDefinition("DELETE_OBJECT", "ACTION", "Delete Object", "Delete an existing object in the database", DeleteObjectExecutor, "fa-solid fa-trash"),
    WorkflowNodeDefinition("ENRICH_DATA", "ACTION", "Enrich Data", "Enriches the input data with additional fields", EnrichExecutor, "fa-solid fa-magic"),
    WorkflowNodeDefinition("EXTRACT_FIELD", "ACTION", "Extract Field", "Extracts a field from the incoming value", ExtractFieldExecutor, "fa-solid fa-code"),
    WorkflowNodeDefinition("CALL_API", "ACTION", "Call API", "Makes an external API call", CallApiExecutor, "fa-solid fa-cloud-arrow-up"),
    WorkflowNodeDefinition("LIST_OBJECTS", "ACTION", "List Objects", "List different objects", ListObjectsExecutor, "fa-solid fa-list"),
    WorkflowNodeDefinition("SEND_USER_MESSAGE", "ACTION", "Send User Message", "Send a message to a user", SendUserMessage, "fa-solid fa-message"),
    WorkflowNodeDefinition("GENERATE_PDF", "ACTION", "Generate PDF", "Generate a pdf from a document template", GeneratePdfExecutor, "fa fa-file-pdf"),
    WorkflowNodeDefinition("SQL_QUERY", "ACTION", "SQL Query", "Execute a raw SQL query against the database", SqlQueryActionExecutor, "fa-solid fa-database"),
    WorkflowNodeDefinition("COMPUTE", "ACTION", "Compute", "Compute a value using a custom Python function", ComputeExecutor, "fa-solid fa-calculator"),
    WorkflowNodeDefinition("HUMAN_IN_THE_LOOP", "ACTION", "Human in the Loop", "Pauses the workflow and waits for a human to provide input", HumanInTheLoopExecutor, "fa-solid fa-hand-paper"),
    WorkflowNodeDefinition("WAIT", "ACTION", "Wait", "Pauses the workflow for a certain amount of seconds", WaitExecutor, "fa-solid fa-clock"),
    WorkflowNodeDefinition("IF_CONDITION", "FLOW", "If Condition", "Routes input through a true or false output", IfConditionExecutor, "fa-solid fa-code-branch"),
    WorkflowNodeDefinition("FILTER_OBJECTS", "FLOW", "Filter Objects", "Filters a collection of objects based on field values", FilterObjectsExecutor, "fa-solid fa-filter"),
    WorkflowNodeDefinition("FOR_EACH", "FLOW", "For Each", "Runs the downstream branch once for each item in a collection", ForEachExecutor, "fa-solid fa-repeat"),
    WorkflowNodeDefinition("COLLECT", "FLOW", "Collect", "Collects all results from a For Each into one ordered list", CollectExecutor, "fa-solid fa-layer-group"),
    WorkflowNodeDefinition("MERGE_BRANCHES", "FLOW", "Merge Branches", "Waits for all upstream branches, then passes their outputs downstream as one object", MergeBranchExecutor, "fa-solid fa-code-merge"),
    WorkflowNodeDefinition("OBJECT_IF_CONDITION", "FLOW", "Object If Condition", "Routes an object through a true or false output", ObjectIfConditionExecutor, "fa-solid fa-code-branch"),
    WorkflowNodeDefinition(
        "RUN_WORKFLOW",
        "ACTION",
        "Run workflow",
        "Run's another workflow with this workflow's input data",
        executor_cls=RunWorkflowExecutor,
        icon="fa-solid fa-code-branch"
    )
]

for workflow_node in WORKFLOW_NODES:
    WORKFLOW_NODE_REGISTRY.register(workflow_node.id, workflow_node)


def workflow_node_type_choices() -> list[tuple[str, str]]:
    return [
        (node_type, WORKFLOW_NODE_TYPE_METADATA[node_type]["name"])
        for node_type in WORKFLOW_NODE_TYPES
    ]


def workflow_node_sub_type_choices() -> list[tuple[str, str]]:
    """Return node choices lazily so extension registrations are included."""
    return WORKFLOW_NODE_REGISTRY.choices()
