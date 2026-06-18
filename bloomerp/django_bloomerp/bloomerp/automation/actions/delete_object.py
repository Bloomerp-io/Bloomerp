from django.forms import modelform_factory
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueType, WorkflowInputRequirement, WorkflowValueField, WorkflowValueType
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.automation.base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django import forms


class ConfigParamsForm(BaseContentTypeForm):
    object_id = forms.CharField(
        required=True,
        label="Object ID",
        help_text="The ID of the object to delete.",
    )
    
    
class DeleteObjectExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.OBJECT
    )
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.OBJECT,
        label="Result",
        description="The result of the delete operation.",
        fields=[
            WorkflowValueField(
                path="status",
                label="Status",
                value_type=WorkflowValueType.STRING,
            ),
            WorkflowValueField(
                path="error_message",
                label="Error Message",
                description="If the delete operation failed, this will contain the error message.",
                value_type=WorkflowValueType.STRING,
                optional=True
            ),
            WorkflowValueField(
                path="deleted_object_id",
                label="Deleted Object ID",
                description="The ID of the deleted object.",
                value_type=WorkflowValueType.STRING,
                optional=True
            )
        ]
    )
    
    def execute(self, input_data: dict) -> dict:
        params = self.resolve_config(input_data)

        # Get the content type ID and object ID from the config
        content_type_id = params.get("content_type_id")
        object_id = params.get("object_id")
        
        try:
            content_type = ContentType.objects.get(id=content_type_id)
            ModelCls = content_type.model_class()
            ModelCls.objects.get(id=object_id).delete()
            
            return {
                "status": "success",
                "deleted_object_id": object_id
            }
        except Exception as e:
            return {
                "status": "error",
                "error_message": str(e)
            }
    
    
        
