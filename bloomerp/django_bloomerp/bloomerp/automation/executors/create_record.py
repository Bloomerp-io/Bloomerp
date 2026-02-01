from django.forms import modelform_factory
from .base import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from dataclasses import dataclass


class ConfigParams:
    content_type_id:int|str
    

class CreateRecordExecutor(BaseExecutor):
    def execute(self, input_data: dict) -> dict:
        # Get the content type id
        params : dict = self.config.get("parameters", {})
        content_type_id = params.get("content_type_id")
        
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
    