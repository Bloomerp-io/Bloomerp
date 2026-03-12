from django.forms import modelform_factory
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from ..base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django import forms
from django.db.utils import OperationalError, ProgrammingError

class ConfigParamsForm(forms.Form):
    content_type_id = forms.IntegerField(
        widget=ForeignFieldWidget(
            {
                "is_m2m" : False,
            }            
        )
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
    

class CreateObjectExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        content_type_id = self.config.get("content_type_id")
        
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
            return {"status": "error"}
    