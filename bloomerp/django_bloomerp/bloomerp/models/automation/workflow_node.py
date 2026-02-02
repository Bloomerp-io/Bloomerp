from typing import Optional
from django.db import models
from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.automation.defintion import NodeTypeDefinition
from bloomerp.automation.defintion import NodeSubTypeDefinition
from bloomerp.automation.base_executor import NodeExecutionError
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import TimestampedModelMixin
from django.utils.translation import gettext_lazy as _
from django.db.models import QuerySet
from django.core.exceptions import ValidationError

class WorkflowNode(
    UserStampedModelMixin,
    TimestampedModelMixin,
    models.Model):
    
    class Meta:
        db_table = "bloomerp_workflow_node"
        verbose_name = _("Workflow Node")
        verbose_name_plural = _("Workflow Nodes")
    
    workflow = models.ForeignKey(
        to="bloomerp.Workflow",
        on_delete=models.CASCADE,
        related_name="nodes"
    )
    
    type = models.CharField(
        max_length=32,
        choices=WorkflowNodeType.choices(),
        help_text=_("The type of the workflow node.")
    )
    
    config : dict = models.JSONField(
        default=dict,
        help_text=_("The configuration for the workflow node.")
    )
    
    # UI position fields
    pos_x = models.IntegerField(
        help_text=_("The X position of the node in the workflow editor."),
        default=0
        )
    pos_y = models.IntegerField(
        help_text=_("The Y position of the node in the workflow editor."),
        default=0
        )

    @property
    def node_type(self) -> NodeTypeDefinition:
        """Returns the NodeTypeDefinition for this node.

        Returns:
            NodeTypeDefinition: The definition of the node type.
        """
        return WorkflowNodeType[self.type].value
    
    @property
    def node_sub_type_id(self):
        return self.config.get("sub_type")
    
    @property
    def node_sub_type(self) -> Optional[NodeSubTypeDefinition]:
        """Returns the NodeSubTypeDefinition for this node.

        Returns:
            Optional[NodeSubTypeDefinition]: The definition of the node sub-type, or None if not found.
        """
        for sub_type in self.node_type.types:
            if isinstance(sub_type, NodeSubTypeDefinition) and sub_type.id == self.node_sub_type_id:
                return sub_type
        return None
    
    def get_output_nodes(self) -> models.QuerySet["WorkflowNode"]:
        """Returns the output nodes connected to this node.

        Returns:
            models.QuerySet[WorkflowNode]: The output nodes.
        """
        return WorkflowNode.objects.filter(
            incoming_edges__from_node=self
        )
        
    def execute(self, trigger_data:dict) -> dict:
        """Executes the node's action.

        Args:
            trigger_data (dict): The data from the trigger that initiated the workflow.
            
        Returns:
            dict: The output data from the node execution.
        """
        # Placeholder for node execution logic
        sub_type = self.node_sub_type
        
        if sub_type and sub_type.executor_cls:
            executor = sub_type.executor_cls(self.config)
            output = executor.execute(trigger_data)
            return output
        
        raise NodeExecutionError(f"Node subtype not found for node")
    
    def clean(self):
        """Ensure only one trigger node is allowed per workflow."""
        super().clean()
        errors = {}
        
        if self.type == WorkflowNodeType.TRIGGER.value.id:
            existing_triggers = WorkflowNode.objects.filter(
                workflow=self.workflow,
                type=WorkflowNodeType.TRIGGER.value.id
            ).exclude(id=self.id)

            if existing_triggers.exists():
                errors["type"] = _(f"Only one trigger node is allowed per workflow. Workflow '{self.workflow.name}' already has a trigger.")

        if not self.node_sub_type_id:
            errors["config"] = _("Node subtype is required in config")
        else:
            if not self.node_sub_type:
                errors["config"] = _(f"Node subtype of id '{self.node_sub_type_id}' does not exist.")
                
        # Raise if there are errors
        if errors:
            raise ValidationError(errors)
        
    def save(self, *args, **kwargs):
        self.full_clean()  # Ensure validations are run
        return super().save(*args, **kwargs)
        
    @staticmethod
    def get_triggers_by_type(trigger_subtype: str) -> QuerySet["WorkflowNode"]:
        """Returns all of the triggers by subtype

        Args:
            trigger_subtype (str): The subtype ID of the trigger, referring to the 'id' defined in definitions.

        Returns:
            QuerySet["WorkflowNode"]: QuerySet of WorkflowNode objects matching the trigger subtype.
        """
        return WorkflowNode.objects.filter(config__sub_type=trigger_subtype)





