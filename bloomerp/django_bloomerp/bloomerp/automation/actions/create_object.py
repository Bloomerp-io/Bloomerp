import json

from django.forms import modelform_factory
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from ..base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django import forms
from django.db.utils import OperationalError, ProgrammingError


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

class ConfigParamsForm(forms.Form):
    content_type_id = forms.IntegerField(
        widget=ForeignFieldWidget(
            {
                "is_m2m" : False,
                "class" : "input w-full"
            }            
        )
    )
    
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json",
        ),
        initial=dict
    )
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            application_field = ApplicationField.objects.filter(
                field="content_type"
            ).first()
            self.fields["content_type_id"].widget.attrs.update(application_field.meta if application_field else {})
        except (OperationalError, ProgrammingError):
            self.fields["content_type_id"].widget.attrs.update({})

        if self.initial.get("content_type_id") and not self.initial.get("data"):
            default_data = _build_default_data(self.initial.get("content_type_id"))
            self.initial["data"] = default_data
            self.fields["data"].initial = default_data
        
class CreateObjectExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        content_type_id = self.config.get("content_type_id")
        
        params = self.resolve_config(input_data)
        print("Resolved params", params)
        
        # Get the content type ID
        content_type = ContentType.objects.get(id=content_type_id)

        # Get the model
        model = content_type.model_class()
        
        FormCls = modelform_factory(
            model=model,
            fields=input_data.keys()
        )
        
        form = FormCls(input_data)
        if form.is_valid():
            form.save()
            return {"status" : "object_created"}
        else:
            print(form.errors)
            return {"status": "error"}
    
    
    
        