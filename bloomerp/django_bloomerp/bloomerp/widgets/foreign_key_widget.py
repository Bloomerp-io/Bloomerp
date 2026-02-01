import json

from django.forms import widgets
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType

class ForeignFieldWidget(widgets.Widget):
    template_name = 'widgets/foreign_field_widget.html'
    is_m2m: bool = False
    
    def __init__(self, attrs=None):
        self.is_m2m = attrs.pop('is_m2m', False) if attrs else False
        self.model = attrs.pop('model', None) if attrs else None
        super().__init__(attrs)
    
    def get_context(self, name, value:Model, attrs):
        context = super().get_context(name, value, attrs)
        
        # Add the content type ID to the context
        if self.model:
            context['content_type_id'] = ContentType.objects.get_for_model(self.model).id
        elif value and hasattr(value, '_meta'):
            context['content_type_id'] = ContentType.objects.get_for_model(value._meta.model).id
        else:
            raise ValueError("ForeignFieldWidget requires either 'model' to be set or a value with _meta attribute")


        # Check if an invalid entry was made
        if (attrs or {}).get('aria-invalid', 'false') == 'true':
            context['invalid'] = True
        
        # Set selected value(s)
        selected_ids = []
        selected_labels = []

        if value is not None:
            if self.is_m2m:
                if hasattr(value, 'all'):
                    items = list(value.all())
                elif isinstance(value, (list, tuple, set)):
                    items = list(value)
                else:
                    items = [value]

                for item in items:
                    if isinstance(item, Model):
                        selected_ids.append(item.pk)
                        selected_labels.append(str(item))
                    else:
                        selected_ids.append(item)
                        selected_labels.append(str(item))
            else:
                if isinstance(value, Model):
                    selected_ids = [value.pk]
                    selected_labels = [str(value)]
                else:
                    selected_ids = [value]
                    selected_labels = [str(value)]

        context['selected_value'] = selected_ids[0] if selected_ids else ''
        context['selected_ids_json'] = json.dumps([str(v) for v in selected_ids])
        context['selected_labels_json'] = json.dumps([str(v) for v in selected_labels])
        
        return context
