from bloomerp.automation.triggers.base import BaseTrigger
from django import forms
from django.contrib.contenttypes.models import ContentType

from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

class ObjectCrudTriggerForm:
    model = forms.ModelChoiceField(
        queryset=ContentType.objects.all(),
        widget=ForeignFieldWidget(attrs={
            "is_m2m" : False
        })
    )


class ObjectCrudTrigger(BaseTrigger):
    config_form = ObjectCrudTriggerForm
    