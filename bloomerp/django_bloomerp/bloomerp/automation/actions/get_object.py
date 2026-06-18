

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueField, WorkflowValueType
from bloomerp.automation.utils import model_to_schema_field
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from django import forms

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django.contrib.contenttypes.models import ContentType

class GetObjectConfigForm(BaseContentTypeForm):
    """
    Form to configure the GetObject action
    """
    refresh_on_input = True
    
    object_id = forms.CharField(
        widget=forms.HiddenInput(),
        label="Object ID",
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if self.field_is_set("content_type_id"):
            content_type = ContentType.objects.get(id=self.initial["content_type_id"])
            
            self.fields["object_id"].widget = ForeignFieldWidget(
                model=content_type.model_class(),
                attrs={
                    "class" : "input w-full",
                }
            )
                        
class GetObjectExecutor(BaseExecutor):
    """
    Executor for the GetObject action
    """
    config_form = GetObjectConfigForm
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.OBJECT,
        label="Object",
        description="Returns the object specified by the content type and object ID in the configuration.",
        fields=[]
    )
    
    
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        content_type_id = (config or {}).get("parameters", {}).get("content_type_id")
        if content_type_id is None:
            return cls.output_schema
        
        try:
            ModelCls = ContentType.objects.get(id=content_type_id).model_class()
        except ContentType.DoesNotExist:
            return cls.output_schema
        
        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label="Object", 
            description="Returns the object specified by the content type and object ID in the configuration.",
            fields=[
                model_to_schema_field(model=ModelCls, optional=True),
                WorkflowValueField(
                    path="found",
                    label="Found",
                    description="Indicates whether the object was found or not.",
                    value_type=WorkflowValueType.BOOLEAN,
                    optional=False,
                )
            ]
        )
    
    def execute(self, input_data:dict) -> dict:
        params = self.resolve_config(input_data)
        
        try:
            content_type = ContentType.objects.get(id=params.get("content_type_id"))
            model_class = content_type.model_class()
            object_id = model_class._meta.pk.to_python(params.get("object_id"))
            
            obj = model_class.objects.filter(id=object_id).first()
            
            return {
                "instance": {
                    field.name: getattr(obj, field.name)
                    for field in model_class._meta.fields
                } if obj is not None else None,
                "found": obj is not None,
            }
        
        except Exception as e:
            # Log the exception
            return {
                "instance": None,
                "found": False,
            }
