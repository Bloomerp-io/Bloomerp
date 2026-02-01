from dataclasses import dataclass
from typing import Type
from typing import Optional
from django.utils.translation import gettext_lazy as _
from enum import Enum
from bloomerp.automation.executors.base import BaseExecutor
from bloomerp.automation.executors.create_record import CreateRecordExecutor
from bloomerp.automation.triggers.human_trigger import HumanTrigger

@dataclass
class NodeSubTypeDefinition:
    id:str
    name:str = ""
    description:str = ""
    executor_cls:Optional[Type[BaseExecutor]] = None
    

@dataclass
class NodeTypeDefinition:
    id:str
    name:str
    description:str
    types:list[NodeSubTypeDefinition | str]


class WorkflowNodeType(Enum):
    TRIGGER = NodeTypeDefinition(
        id="TRIGGER",
        name=_("Trigger"),
        description=_("The trigger for a workflow"),
        types=[
            NodeSubTypeDefinition(
                id="ON_RECORD_CREATE",
                name="On Record Create",
                description="Triggered when a new record is created",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="ON_RECORD_UPDATE",
                name="On Record Update",
                description="Triggered when a record is updated",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="ON_SCHEDULE",
                name="On Schedule",
                description="Triggered on a defined schedule",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="ON_WEBHOOK",
                name="On Webhook",
                description="Triggered when a webhook is received",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="HUMAN_TRIGGER",
                name="Human Trigger",
                description="Triggered by a human. Used for testing purposes.",
                executor_cls=HumanTrigger
            )
        ]
    )

    ACTION = NodeTypeDefinition(
        id="ACTION",
        name=_("Action"),
        description=_("An action to perform"),
        types=[
            NodeSubTypeDefinition(
                id="SEND_EMAIL",
                name="Send Email",
                description="Sends an email to specified recipients",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="CREATE_RECORD",
                name="Create Record",
                description="Creates a new record in the database",
                executor_cls=CreateRecordExecutor
            ),
            NodeSubTypeDefinition(
                id="UPDATE_RECORD",
                name="Update Record",
                description="Updates an existing record in the database",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="CALL_API",
                name="Call API",
                description="Makes an external API call",
                executor_cls=None  # Placeholder for actual function
            )
        ]
    )

    FLOW = NodeTypeDefinition(
        id="FLOW",
        name=_("Flow"),
        description=_("A flow node to branch the workflow"),
        types=[
            NodeSubTypeDefinition(
                id="IF_CONDITION",
                name="If Condition",
                description="Branches the workflow based on a condition",
                executor_cls=None  # Placeholder for actual function
            ),
            NodeSubTypeDefinition(
                id="SWITCH_CASE",
                name="Switch Case",
                description="Branches the workflow based on multiple conditions",
                executor_cls=None  # Placeholder for actual function
            ),
        ]
    )

    @classmethod
    def choices(cls):
        return [(member.value.id, member.value.name) for member in cls]
    
    @classmethod
    def members(cls):
        return [member for member in cls]