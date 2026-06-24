from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueType, WorkflowInputRequirement, WorkflowValueField, WorkflowValueType
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from ..base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django import forms


class ConfigParamsForm(forms.Form):
    document_template = forms.ModelChoiceField(
        queryset=DocumentTemplate.objects.all(),
        widget=ForeignFieldWidget(
            model=DocumentTemplate,
            attrs={
                "class" : "input w-full"
            }
        )
    )
    data = forms.JSONField(
        required=True,
        label="Enrichment Data",
        widget=CodeEditorWidget(
            language="json",
        )
    )

    
class GeneratePdfExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.ANY,
        label="Any object",
    )
    
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.OBJECT,
        fields=[
            WorkflowValueField(
                path="pdf_url", 
                label="PDF URL", 
                description="The generated URL of the PDF file.",
                value_type=WorkflowValueType.STRING,
            ),
            WorkflowValueField(
                path="file_id", 
                label="File ID", 
                description="The ID of the generated PDF file.",
                value_type=WorkflowValueType.STRING,
            ),
        ],
    )
    
    
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        
        
        return input_data
    
    
    
        
