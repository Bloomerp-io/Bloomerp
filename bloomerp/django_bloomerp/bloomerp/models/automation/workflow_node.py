from django.db import models
from bloomerp.automation.registry import (
    WORKFLOW_NODE_REGISTRY,
    WorkflowNodeDefinition,
    workflow_node_sub_type_choices,
    workflow_node_type_choices,
)
from bloomerp.automation.base_executor import BaseExecutor, NodeExecutionError
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins import TimestampModelMixin
from django.utils.translation import gettext_lazy as _
from django.db.models import QuerySet
from django.core.exceptions import ValidationError

class WorkflowNode(
    UserStampModelMixin,
    TimestampModelMixin,
    AbsoluteUrlModelMixin,
    models.Model,
    ):
    
    class Meta:
        db_table = "bloomerp_workflow_node"
        verbose_name = _("Workflow Node")
        verbose_name_plural = _("Workflow Nodes")
            
    # TODO: Integrate name with builder
    name = models.CharField(
        max_length=255,
        help_text=_("The name of the workflow node."),
        null=True,
        blank=True,
        verbose_name=_("Name"),
    )
    workflow = models.ForeignKey(
        to="bloomerp.Workflow",
        on_delete=models.CASCADE,
        related_name="nodes",
        verbose_name=_("Workflow"),
    )
    
    type = models.CharField(
        max_length=32,
        choices=workflow_node_type_choices,
        help_text=_("The type of the workflow node."),
        verbose_name=_("Type"),
    )
    
    sub_type = models.CharField(
        max_length=100,
        choices=workflow_node_sub_type_choices,
        db_index=True,
        help_text=_("The registered subtype of the workflow node."),
        verbose_name=_("Sub Type"),
    )

    parameters: dict = models.JSONField(
        blank=True,
        default=dict,
        help_text=_("The parameters for the workflow node."),
        verbose_name=_("Parameters"),
    )
    
    # UI position fields
    pos_x = models.IntegerField(
        help_text=_("The X position of the node in the workflow editor."),
        default=0,
        verbose_name=_("Pos X"),
        )
    pos_y = models.IntegerField(
        help_text=_("The Y position of the node in the workflow editor."),
        default=0,
        verbose_name=_("Pos Y"),
        )

    @property
    def node_sub_type_id(self):
        return self.sub_type
    
    @property
    def node_sub_type(self) -> WorkflowNodeDefinition | None:
        """Return the registered definition for this node.

        Returns:
            WorkflowNodeDefinition: The registered node definition, when found.
        """
        return WORKFLOW_NODE_REGISTRY.get(self.sub_type)
    
    def get_executor(self) -> BaseExecutor:
        """Instantiate the executor registered for this node."""
        definition = self.node_sub_type
        if definition and definition.executor_cls:
            return definition.executor_cls(self.parameters)
        raise NodeExecutionError("Node subtype not found for node")

    def get_output_ports(self) -> tuple[WorkflowNodeOutputPort, ...]:
        """Return the static or configuration-driven ports for this node."""
        return self.get_executor().get_output_ports(self.parameters or {})

    def get_output_nodes(
        self,
        *,
        port_id: str = "default",
    ) -> models.QuerySet["WorkflowNode"]:
        """Returns the output nodes connected to this node.

        Returns:
            models.QuerySet[WorkflowNode]: The output nodes.
        """
        return WorkflowNode.objects.filter(
            incoming_edges__from_node=self,
            incoming_edges__output_port=port_id,
        )
    
    def get_input_nodes(self) -> models.QuerySet["WorkflowNode"]:
        """Returns the input nodes connected to this node.

        Returns:
            models.QuerySet[WorkflowNode]: The input nodes.
        """
        return WorkflowNode.objects.filter(
            outgoing_edges__to_node=self
        )
        
    
    def execute(self, trigger_data:dict) -> dict:
        """Executes the node's action.

        Args:
            trigger_data (dict): The data from the trigger that initiated the workflow.
            
        Returns:
            dict: The output data from the node execution.
        """
        # Placeholder for node execution logic
        return self.get_executor().execute(trigger_data)
    
    def clean(self):
        """Ensure only one trigger node is allowed per workflow."""
        super().clean()
        errors = {}
        
        if self.type == "TRIGGER":
            existing_triggers = WorkflowNode.objects.filter(
                workflow=self.workflow,
                type="TRIGGER"
            ).exclude(id=self.id)

            if existing_triggers.exists():
                errors["type"] = _(f"Only one trigger node is allowed per workflow. Workflow '{self.workflow.name}' already has a trigger.")

        if not self.sub_type:
            errors["sub_type"] = _("Node subtype is required")
        else:
            definition = self.node_sub_type
            if definition is None:
                errors["sub_type"] = _(
                    f"Node subtype of id '{self.sub_type}' does not exist."
                )
            elif definition.type != self.type:
                errors["sub_type"] = _(
                    f"Node subtype '{self.sub_type}' belongs to type "
                    f"'{definition.type}', not '{self.type}'."
                )
                
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
        return WorkflowNode.objects.filter(sub_type=trigger_subtype)

    
    
