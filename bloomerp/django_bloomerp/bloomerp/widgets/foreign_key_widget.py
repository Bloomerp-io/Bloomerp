from django import forms
from django.forms.models import modelform_factory
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
import random

class ForeignFieldWidget(forms.Widget):
    template_name = 'widgets/foreign_field_widget.html'

    def __init__(self, model: Model, *args, **kwargs):
        self.model = model
        self.is_m2m = kwargs.pop('is_m2m', False)
        super().__init__(*args, **kwargs)
    
    def get_context(self, name, value, attrs):
        from bloomerp.models import ApplicationField
        context = super().get_context(name, value, attrs)
        
        # Add the content type ID to the context        
        context['content_type_id'] = ContentType.objects.get_for_model(self.model).id

        # Get the object that is currently selected
        if context['widget']['value']:
            context['selected_object'] = self.model.objects.get(pk=context['widget']['value'])

        # Check if an invalid entry was made
        if attrs.get('aria-invalid', 'false') == 'true':
            context['invalid'] = True
            
        return context
