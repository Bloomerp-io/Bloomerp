from django import forms
from django.db import OperationalError, ProgrammingError

from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

class BaseContentTypeForm(BaseWorkflowNodeForm):
    """
    Base form that conatains a content type input
    """
    content_type_id = forms.IntegerField(
        widget=ForeignFieldWidget(
            {
                "class" : "input w-full",
                "is_m2m" : False,
            }            
        ),
        label="Model",
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