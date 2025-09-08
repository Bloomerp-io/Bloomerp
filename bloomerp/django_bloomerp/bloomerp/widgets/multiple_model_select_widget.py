from django import forms
from django.forms.models import modelform_factory
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
import random
class MultipleModelSelect(forms.SelectMultiple):
    template_name = 'widgets/foreign_field_widget.html'

    def __init__(self, model: Model, *args, **kwargs):
        self.model = model
        super().__init__(*args, **kwargs)
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # Create new form in case user wants to update the foreign key
        Form = modelform_factory(self.model, fields='__all__')
        
        # Get first 5 objects from the model
        context['objects'] = self.model.objects.all()[:5]
        context['content_type_id'] = ContentType.objects.get_for_model(self.model).id
        context['form'] = Form()

        # Add random modal id to the context
        context['advanced_search_modal_id'] = f'modal-{random.randint(0, 100000)}'
        context['create_modal_id'] = f'modal-{random.randint(0, 100000)}'

        # Get the object(s) that is currently selected
        if context['widget']['value']:
            values : str = context['widget']['value']
            selected_choices = self.model.objects.filter(pk__in=values)
            context['selected_choices'] = selected_choices

        # Check if an invalid entry was made
        if attrs.get('aria-invalid', 'false') == 'true':
            context['invalid'] = True

        # Add application fields to the context
        context['application_fields'] = ApplicationField.objects.filter(content_type=ContentType.objects.get_for_model(self.model)).exclude(field_type='Property')

        context['widget_type'] = 'm2m'
        return context
    
        
        


