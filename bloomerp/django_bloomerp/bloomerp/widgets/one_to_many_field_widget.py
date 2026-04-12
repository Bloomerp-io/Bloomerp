from django.forms import widgets
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
import json

class OneToManyFieldWidget(widgets.Widget):
    template_name = 'widgets/one_to_many_field_widget.html'
    related_model: Model = None
    fields: list = []
    
    def __init__(self, attrs=None):
        self.related_model = attrs.pop('related_model', None) if attrs else None
        self.fields = attrs.pop('fields', []) if attrs else []
        super().__init__(attrs)
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        
        # Get content type ID for the related model
        if self.related_model:
            context['content_type_id'] = ContentType.objects.get_for_model(self.related_model).id
        else:
            context['content_type_id'] = None
        
        # Get the related objects
        related_objects = []
        if value is not None:
            if hasattr(value, 'all'):  # QuerySet
                related_objects = list(value.all())
            elif isinstance(value, (list, tuple, set)):
                related_objects = list(value)
            else:
                related_objects = [value]
        
        context['related_objects'] = related_objects
        context['fields'] = self.fields
        
        return context
