import json

from django.forms import modelform_factory
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueType, WorkflowInputRequirement, WorkflowValueField, WorkflowValueType
from bloomerp.automation.utils import get_parameters_from_config, model_to_schema_field
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.automation.base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django import forms


def _get_json_safe_default(model_field) -> object | None:
    if not model_field.has_default():
        return None

    default = model_field.default
    if callable(default):
        if default in {dict, list, tuple, set}:
            value = default()
        else:
            return None
    else:
        value = default

    if isinstance(value, tuple | set):
        value = list(value)

    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _build_default_data(content_type_id: int) -> dict[str, object | None]:
    default_data: dict[str, object | None] = {}
    fields = ApplicationField.objects.filter(content_type_id=content_type_id)
    fields.exclude(field__in=[
        "datetime_created",
        "datetime_updated",
    ])
    
    
    for field in fields:
        if not field.get_field_type_enum().value.allow_in_model:
            continue

        form_field = field.get_form_field()
        if form_field is None:
            continue

        model_field = field._get_model_field()
        default_data[field.field] = _get_json_safe_default(model_field)

    return default_data

class ConfigParamsForm(BaseContentTypeForm):
    
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json",
        ),
        initial=dict
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.initial.get("content_type_id") and not self.initial.get("data"):
            default_data = _build_default_data(self.initial.get("content_type_id"))
            self.initial["data"] = default_data
            self.fields["data"].initial = default_data

    
class CreateObjectExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.OBJECT
    )
    
    # OK
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        params = get_parameters_from_config(config)
        
        # Get the content type ID
        content_type_id = params.get("content_type_id")
        ModelCls = None
        if content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                ModelCls = content_type.model_class()
            except (ContentType.DoesNotExist, ValueError, TypeError):
                ModelCls = None
        
        instance = None
        if ModelCls is not None:
            instance = model_to_schema_field(ModelCls, optional=True)
        
        fields = [
            WorkflowValueField(
                path="status",
                label="Status",
                value_type=WorkflowValueType.STRING,
            ),
            WorkflowValueField(
                path="error_message",
                label="Error Message",
                value_type=WorkflowValueType.LIST,
                optional=True,
                children=[
                    WorkflowValueField(
                        path="field",
                        label="Field",
                        value_type=WorkflowValueType.STRING,
                    ),
                    WorkflowValueField(
                        path="messages",
                        label="Messages",
                        value_type=WorkflowValueType.LIST,
                        children=[
                            WorkflowValueField(
                                path="message",
                                label="Message",
                                value_type=WorkflowValueType.STRING,
                            )
                        ]
                    )
                ]
            )
        ]
        
        if instance:
            fields.insert(0, instance)
        
        return WorkflowIOSchema(
            value_type=WorkflowValueType.OBJECT,
            fields=fields
        )
    
    # TODO: Handle M2M and O2M relationships in the input data
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        content_type_id = self.config.get("content_type_id")

        # Get the content type ID
        content_type = ContentType.objects.get(id=content_type_id)
        
        # Get the model
        model = content_type.model_class()

        resolved_config = self.resolve_config(input_data)
        create_data = resolved_config.get("fields")
        if create_data is None:
            create_data = resolved_config.get("data")
        if create_data is None:
            create_data = input_data
        if not isinstance(create_data, dict):
            create_data = {}
        
        FormCls = bloomerp_modelform_factory(model, fields=create_data.keys())
        
        form = FormCls(create_data)
        if form.is_valid():
            object = form.save()
            return {
                "status": "success",
                "instance": object,
                "error_message": None,
            }
        else:
            error_messages = []
            for field, errors in form.errors.items():
                error_messages.append({
                    "field": field,
                    "messages": [{"message": str(error)} for error in errors]
                })
            return {
                "status": "error",
                "instance": None,
                "error_message": error_messages
            }
    
    
    
        
