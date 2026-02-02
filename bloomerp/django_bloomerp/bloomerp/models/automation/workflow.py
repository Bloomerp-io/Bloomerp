from typing import TYPE_CHECKING
from django.db import models
from bloomerp.models.mixins import UserStampedModelMixin
from bloomerp.models.mixins import TimestampedModelMixin
from django.utils.translation import gettext_lazy as _
from bloomerp.automation.defintion import WorkflowNodeType

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_node import WorkflowNode
    from bloomerp.models.automation.workflow_edge import WorkflowEdge

class Workflow(
    UserStampedModelMixin,
    TimestampedModelMixin,
    models.Model):
    """
    A workflow is a model for automation.
    Each workflow can have differnent nodes.
    """
    class Meta:
        db_table = "bloomerp_workflow"
        verbose_name = _("Workflow")
        verbose_name_plural = _("Workflows")
    
    name = models.CharField(
        max_length=255,
        help_text=_("The name of the workflow.")
        )
    
    def get_trigger(self) -> "WorkflowNode":
        """Returns the trigger of a workflow.

        Returns:
            WorkflowNode: the triggering node of this workflow
        """
        nodes: models.QuerySet["WorkflowNode"] = self.nodes.all()

        return nodes.filter(
            type=WorkflowNodeType.TRIGGER.value.id
        ).first()
        
    def contains_node(self, node:"WorkflowNode") -> bool:
        """Checks whether a workflow contains a node object

        Args:
            node (WorkflowNode): _description_

        Returns:
            bool: whether it contains the node
        """
        pass
    
    def connect_nodes(self, input_node:"WorkflowNode", output_node:"WorkflowNode") -> "WorkflowEdge":
        """Adds a connection between two nodes.

        Args:
            input_node (WorkflowNode): the input node
            output_node (WorkflowNode): the output node 
        
        Returns:
            edge : the edge between the two nodes
        """
        if not self.contains_node(input_node):
            raise ValueError("Node not in workflow")
        
        
        
        
        
