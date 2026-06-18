from bloomerp.automation.utils import model_fields_to_value_fields
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.models.application_field import ApplicationField
from bloomerp.utils.filters import filter_model
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.list_filter_widget import ListFilterWidget
from ..base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django import forms
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    WorkflowValueType,
)

class ConfigParamsForm(BaseContentTypeForm):
    filters = forms.JSONField(
        required=False,
        widget=CodeEditorWidget(
            language="json",
        ),
        initial=dict,
        help_text="Optional filters to apply to the queryset. Should be a JSON object where keys are field names and values are the values to filter by. For example: {\"status\": \"active\"} would filter the queryset to only include objects where the 'status' field is 'active'. You can also use Django's double underscore notation for related fields, e.g. {\"user__username\": \"john\"} would filter by the username of a related user object.",
    )
    
    

class ListObjectsExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    input_requirement = WorkflowInputRequirement(
        value_type="any",
        label="Any input",
        description="The incoming data is not used by this action.",
    )
    
    
    def execute(self, input_data: dict) -> list[dict]:
        # Get the content type id
        content_type_id = self.config.get("content_type_id")
        filter_config = self.config.get("filters")
        
        # Get the content type ID
        ModelCls = ContentType.objects.get(id=content_type_id).model_class()
        queryset = ModelCls.objects.all()
        
        if filter_config:
            config = self.resolve_config(input_data)
            
            queryset = filter_model(
                ModelCls,
                config.get("filters"),
                queryset
            )
        
        return {
            "queryset" : [
                {
                    field.name: getattr(obj, field.name)
                    for field in ModelCls._meta.fields
                }
                for obj in queryset
            ],
            "count": queryset.count(),
            "content_type_id": content_type_id,
        }

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
    ) -> WorkflowIOSchema:
        content_type_id = (config or {}).get("parameters", {}).get("content_type_id")
        if not content_type_id:
            return cls.output_schema

        try:
            content_type = ContentType.objects.get(id=content_type_id)
        except (ContentType.DoesNotExist, ValueError, TypeError):
            return cls.output_schema

        model = content_type.model_class()
        if model is None:
            return cls.output_schema

        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            label=str(model._meta.verbose_name_plural).title(),
            description=f"A list of {model._meta.verbose_name_plural}.",
            fields=[
                WorkflowValueField(
                    path="count",
                    label="Count",
                    value_type=WorkflowValueType.NUMBER,
                ),
                WorkflowValueField(
                    path="content_type_id",
                    label="Content Type ID",
                    value_type=WorkflowValueType.NUMBER,
                ),
                WorkflowValueField(
                    path="queryset", 
                    label=f"{model._meta.verbose_name_plural.title()} List", 
                    value_type=WorkflowValueType.LIST,
                    children=model_fields_to_value_fields(model, path_prefix="queryset.0"),
                ),
            ],
        )

    
    
