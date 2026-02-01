from typing import Optional
from django.db import models
from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.automation.defintion import NodeTypeDefinition
from bloomerp.automation.defintion import NodeSubTypeDefinition
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import TimestampedModelMixin
from django.utils.translation import gettext_lazy as _

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
        help_text=_("The X position of the node in the workflow editor.")
        )
    pos_y = models.IntegerField(
        help_text=_("The Y position of the node in the workflow editor.")
        )

    @property
    def node_type(self) -> NodeTypeDefinition:
        """Returns the NodeTypeDefinition for this node.

        Returns:
            NodeTypeDefinition: The definition of the node type.
        """
        return WorkflowNodeType[self.type].value
    
    @property
    def node_sub_type(self) -> Optional[NodeSubTypeDefinition]:
        """Returns the NodeSubTypeDefinition for this node.

        Returns:
            Optional[NodeSubTypeDefinition]: The definition of the node sub-type, or None if not found.
        """
        sub_type_name = self.config.get("sub_type")
        for sub_type in self.node_type.types:
            if isinstance(sub_type, NodeSubTypeDefinition) and sub_type.name == sub_type_name:
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
        
        return {}
        
    
    
    
    
    