from django import forms
from typing import Type
from django.db.models import Model
from bloomerp.models import ApplicationField
from bloomerp.field_types import FieldType

def bloomerp_modelform_factory(
    model_cls: Type[Model],
    fields: list[str] | str = "__all__"    
) -> Type[forms.ModelForm]:
    """Creates a Bloomerp ModelForm for the given model class and fields."""
    application_fields = ApplicationField.get_for_model(model_cls)
    
    if not fields == "__all__":
        application_fields = application_fields.filter(
            field__in=fields
        )
    
    exclude_list = [
        field.value.id for field in FieldType
        if not field.value.allow_in_model
    ]
    
    application_fields = application_fields.exclude(
        field_type__in=exclude_list
    )
    
    form_fields = {}
    for application_field in application_fields:
        try:
            form_fields[application_field.field] = application_field.get_form_field()
        except Exception as e:
            continue
        
    MetaCls = type("Meta", (), {"model":model_cls, "fields":fields})
    
    attrs = form_fields
    attrs.update({"Meta": MetaCls})
    
    return type(f"{model_cls._meta.model_name}Form", (forms.ModelForm,),attrs)

    
    
    
    
    


        