from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.automation.ports import DEFAULT_PORT_ID

class WorkflowEdge(
    models.Model):
    """
    An edge connects two nodes in a workflow.
    It defines the flow of execution from one node to another.
    """
    class Meta:
        db_table = "bloomerp_workflow_edge"
        verbose_name = _("Workflow Edge")
        verbose_name_plural = _("Workflow Edges")
    
    name = models.CharField(
        max_length=1000,
        help_text="A descriptive name for the edge.",
        null=True,
        blank=True,
        verbose_name=_("Name"),
    )

    from_node = models.ForeignKey(
        'WorkflowNode',
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
        help_text="The node where this edge starts.",
        verbose_name=_("From Node"),
    )
    
    to_node = models.ForeignKey(
        'WorkflowNode',
        on_delete=models.CASCADE,
        related_name="incoming_edges",
        help_text="The node where this edge ends.",
        verbose_name=_("To Node"),
    )

    output_port = models.CharField(
        max_length=100,
        default=DEFAULT_PORT_ID,
        help_text="The output port on the source node used by this edge.",
        verbose_name=_("Output Port"),
    )

    def clean(self):
        super().clean()
        errors = {}
        if self.from_node_id and self.to_node_id:
            if self.from_node.workflow_id != self.to_node.workflow_id:
                errors["to_node"] = _("Connected nodes must belong to the same workflow.")

        if self.from_node_id:
            ports = {port.id: port for port in self.from_node.get_output_ports()}
            port = ports.get(self.output_port)
            if port is None:
                errors["output_port"] = _(
                    "The selected output port is not available on the source node."
                )
            elif port.max_connections is not None:
                connections = type(self).objects.filter(
                    from_node_id=self.from_node_id,
                    output_port=self.output_port,
                )
                if self.pk:
                    connections = connections.exclude(pk=self.pk)
                if connections.count() >= port.max_connections:
                    errors["output_port"] = _(
                        "This output port has reached its connection limit."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
