from django import forms
from django.forms.models import modelform_factory
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
import random

class ForeignKeyWidget(forms.Widget):
    template_name = 'widgets/foreign_field_widget.html'

    def __init__(self, model: Model, *args, **kwargs):
        self.model = model
        super().__init__(*args, **kwargs)
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # Get first 5 objects from the model
        context['objects'] = self.model.objects.all()[:5]
        context['content_type_id'] = ContentType.objects.get_for_model(self.model).id


        # Create form for the model to be used in the widget
        Form = modelform_factory(self.model, fields='__all__')
        form_prefix = context['widget']['name']
        context['form_prefix'] = form_prefix
        context['form'] = Form(prefix=form_prefix)

        # Add random modal id to the context
        context['advanced_search_modal_id'] = f'modal-{random.randint(0, 100000)}'
        context['create_modal_id'] = f'modal-{random.randint(0, 100000)}'

        # Get the object that is currently selected
        if context['widget']['value']:
            context['selected_object'] = self.model.objects.get(pk=context['widget']['value'])

        # Check if an invalid entry was made
        if attrs.get('aria-invalid', 'false') == 'true':
            context['invalid'] = True

        # Add application fields to the context
        context['application_fields'] = ApplicationField.objects.filter(content_type=ContentType.objects.get_for_model(self.model)).exclude(field_type='Property')

        context['widget_type'] = 'fk'
        return context
