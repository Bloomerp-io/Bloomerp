from django.db import models
from bloomerp.models.automation.workflow import Workflow

class WorkflowEdge(
    models.Model):
    """
    An edge connects two nodes in a workflow.
    It defines the flow of execution from one node to another.
    """
    class Meta:
        db_table = "bloomerp_workflow_edge"
        verbose_name = "Workflow Edge"
        verbose_name_plural = "Workflow Edges"
    
    name = models.CharField(
        max_length=1000,
        help_text="A descriptive name for the edge.",
        null=True,
        blank=True
    )

    from_node = models.ForeignKey(
        'WorkflowNode',
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
        help_text="The node where this edge starts."
    )
    
    to_node = models.ForeignKey(
        'WorkflowNode',
        on_delete=models.CASCADE,
        related_name="incoming_edges",
        help_text="The node where this edge ends."
    )