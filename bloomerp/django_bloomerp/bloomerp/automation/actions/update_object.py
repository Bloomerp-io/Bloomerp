from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowInputRequirement, WorkflowValueField, WorkflowValueType
from bloomerp.automation.utils import get_parameters_from_config, model_to_schema_field
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django.contrib.contenttypes.models import ContentType

class UpdateObjectConfigForm(BaseContentTypeForm):
    refresh_on_input = True
    
    object_id = forms.CharField(
        required=True,
        label="Object ID",
        help_text="The ID of the object to update.",
    )
    
    data = forms.JSONField(
        required=True,
        widget=forms.HiddenInput(),
        initial=dict,
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        content_type_filled = False
        object_id_filled = False
        
        if "content_type_id" in self.initial and self.initial["content_type_id"]:
            self.fields["object_id"].widget = ForeignFieldWidget(
                model=ContentType.objects.get(id=self.initial["content_type_id"]).model_class(),
                attrs={
                    "class" : "input w-full"
                }
            )
            content_type_filled = True    
        
        if "object_id" in self.initial and self.initial["object_id"]:
            object_id_filled = True
            
        if content_type_filled and object_id_filled:
            self.fields["data"].widget = CodeEditorWidget(
                language="json",
            )
            
            #self.refresh_on_input = False
            
    
    
class UpdateObjectExecutor(BaseExecutor):
    config_form = UpdateObjectConfigForm
    input_requirement = WorkflowInputRequirement(
        value_type="any",
        label="Any input",
        description="The incoming data is not used by this action.",
    )
    
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        content_type_id = get_parameters_from_config(config).get("content_type_id")
        content_type = ContentType.objects.get(id=content_type_id) if content_type_id else None
        
        STATUS = WorkflowValueField(
            path="status",
            value_type=WorkflowValueType.STRING,
            label="Status",
            description="The status of the update operation, e.g., 'success' or 'error'."
        )
        ERROR = WorkflowValueField(
            path="error_message",
            label="Error Message",
            description="If the update operation failed, this field contains the error message.",
            value_type=WorkflowValueType.STRING,
            optional=True,
        )
        
        if not content_type:
            return WorkflowIOSchema(
                value_type=WorkflowValueType.OBJECT,
                label="Updated Object",
                description="The updated object after the update operation.",
                fields=[
                    STATUS,
                    ERROR,
                    WorkflowValueField(
                        path="instance",
                        label="Updated Object Data",
                        description="The data of the updated object. The structure of this field depends on the model being updated.",
                        value_type=WorkflowValueType.OBJECT,
                        optional=True,
                    ),
                    
                ]
            )
        
        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="Updated Object",
            description="The updated object after the update operation.",
            fields=[
                STATUS,
                ERROR,
                model_to_schema_field(
                    model=content_type.model_class() if content_type else None,
                    optional=True
                )
            ]
        )
    
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        config = self.resolve_config(input_data)
        content_type_id = config.get("content_type_id")
        object_id = config.get("object_id")
        update_data = config.get("data") or config.get("fields") or {}
        
        # Get the content type ID
        ModelCls = ContentType.objects.get(id=content_type_id).model_class()
        
        FormCls = bloomerp_modelform_factory(ModelCls, fields=update_data.keys())
        try:
            instance = ModelCls.objects.get(id=object_id)
        except ModelCls.DoesNotExist:
            return {
                "status": "error",
                "error_message": f"Object with ID {object_id} does not exist."
            }
            
        form = FormCls(update_data, instance=instance)
        if form.is_valid():
            updated_instance = form.save()
            return {
                "status": "success",
                "instance": {
                    field.name: getattr(updated_instance, field.name)
                    for field in ModelCls._meta.fields
                }
            }
        else:
            return {
                "status": "error",
                "error_message": form.errors.as_text(),
            }
            
        
        
    
        
