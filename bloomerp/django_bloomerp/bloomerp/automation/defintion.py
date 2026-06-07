from dataclasses import dataclass
from typing import Type
from typing import Optional
from django.utils.translation import gettext_lazy as _
from enum import Enum
from bloomerp.automation.actions.list_objects import ListObjectsExecutor
from bloomerp.automation.actions.send_user_message import SendUserMessage
from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.actions.create_object import CreateObjectExecutor
from bloomerp.automation.actions.send_email import SendEmailExecutor
from bloomerp.automation.flows.filter_objects import FilterObjectsExecutor
from bloomerp.automation.flows.for_each import ForEachExecutor
from bloomerp.automation.flows.if_condition import IfConditionExecutor
from bloomerp.automation.triggers.human_trigger import HumanTrigger
from bloomerp.automation.triggers.object_crud_trigger import ObjectCrudTrigger

@dataclass
class NodeSubTypeDefinition:
    id:str
    name:str = ""
    description:str = ""
    executor_cls:Optional[Type[BaseExecutor]] = None
    icon:Optional[str]="fa-solid fa-circle-plus"
    
    
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
                id="ON_OBJECT_CREATE",
                name="On Object Create",
                description="Triggered when a new object is created",
                executor_cls=ObjectCrudTrigger,
                icon="fa-solid fa-circle-plus"
            ),
            NodeSubTypeDefinition( 
                id="ON_OBJECT_UPDATE",
                name="On Object Update",
                description="Triggered when an object is updated",
                executor_cls=ObjectCrudTrigger,
                icon="fa-solid fa-pen-to-square"
            ),
            NodeSubTypeDefinition( 
                id="ON_OBJECT_DELETE",
                name="On Object Deletion",
                description="Triggered when an object is deleted",
                executor_cls=ObjectCrudTrigger,
                icon="fa-solid fa-trash-can"
            ),
            NodeSubTypeDefinition( 
                id="ON_SCHEDULE",
                name="On Schedule",
                description="Triggered on a defined schedule",
                executor_cls=None,  # Placeholder for actual function
                icon="fa-solid fa-clock"
            ),
            # NodeSubTypeDefinition( 
            #     id="ON_WEBHOOK",
            #     name="On Webhook",
            #     description="Triggered when a webhook is received",
            #     executor_cls=None,  # Placeholder for actual function
            #     icon="fa-solid fa-link"
            # ),
            NodeSubTypeDefinition( 
                id="HUMAN_TRIGGER",
                name="Human Trigger",
                description="Triggered by a human. Used for testing purposes.",
                executor_cls=HumanTrigger,
                icon="fa-solid fa-hand-pointer"
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
                executor_cls=SendEmailExecutor,
                icon="fa-solid fa-envelope"
            ),
            NodeSubTypeDefinition(
                id="CREATE_OBJECT",
                name="Create Object",
                description="Creates a new object in the database",
                executor_cls=CreateObjectExecutor,
                icon="fa-solid fa-database"
            ),
            NodeSubTypeDefinition(
                id="UPDATE_OBJECT",
                name="Update Object",
                description="Updates an existing object in the database",
                executor_cls=None,
                icon="fa-solid fa-pen"
            ),
            NodeSubTypeDefinition(
                id="DELETE_OBJECT",
                name="Delete Object",
                description="Delete an existing object in the database",
                executor_cls=None,
                icon="fa-solid fa-trash"
            ),
            NodeSubTypeDefinition(
                id="CALL_API",
                name="Call API",
                description="Makes an external API call",
                executor_cls=None,  # Placeholder for actual function
                icon="fa-solid fa-cloud-arrow-up"
            ),
            NodeSubTypeDefinition(
                id="LIST_OBJECTS",
                name="List Objects",
                description="List different objects",
                executor_cls=ListObjectsExecutor,
                icon="fa-solid fa-list"
            ),
            NodeSubTypeDefinition(
                id="SEND_USER_MESSAGE",
                name="Send User Message",
                description="Send a message to a user",
                executor_cls=SendUserMessage,
                icon="fa-solid fa-message"
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
                description="Continues only when a condition is true",
                executor_cls=IfConditionExecutor,
                icon="fa-solid fa-code-branch"
            ),
            NodeSubTypeDefinition(
                id="FILTER_OBJECTS",
                name="Filter Objects",
                description="Filters a collection of objects based on field values",
                executor_cls=FilterObjectsExecutor,
                icon="fa-solid fa-filter"
            ),
            NodeSubTypeDefinition(
                id="FOR_EACH",
                name="For Each",
                description="Runs the downstream branch once for each item in a collection",
                executor_cls=ForEachExecutor,
                icon="fa-solid fa-repeat"
            ),
            NodeSubTypeDefinition(
                id="SWITCH_CASE",
                name="Switch Case",
                description="Branches the workflow based on multiple conditions",
                executor_cls=None,  # Placeholder for actual function
                icon="fa-solid fa-shuffle"
            ),
        ]
    )

    @classmethod
    def choices(cls):
        return [(member.value.id, member.value.name) for member in cls]
    
    @classmethod
    def members(cls):
        return [member for member in cls]
    
    @classmethod
    def from_id(cls, id):
        for member in cls:
            if member.value.id == id:
                return member
        raise ValueError(f"Unknown node type: {id}")
        
    
