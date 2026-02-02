import json
from django.forms import widgets
from django.db.models import Model
from django.core.exceptions import ObjectDoesNotExist


class ForeignFieldWidget(widgets.Widget):
    template_name = 'widgets/foreign_field_widget.html'
    is_m2m: bool = False
    
    def __init__(self, attrs=None):
        from bloomerp.models.application_field import ApplicationField
        self.is_m2m = attrs.pop('is_m2m', False) if attrs else False
        self.application_field : ApplicationField = attrs.pop('application_field', None) if attrs else None
        super().__init__(attrs)
    
    def get_context(self, name, value:Model, attrs):
        context = super().get_context(name, value, attrs)
        context["content_type_id"] = self.application_field.related_model.id

        # Check if an invalid entry was made
        if (attrs or {}).get('aria-invalid', 'false') == 'true':
            context['invalid'] = True
        
        # Get the related model class
        related_model_class = self.application_field.related_model.model_class()
        
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
                        # Fetch the model instance by ID
                        try:
                            instance = related_model_class.objects.get(pk=item)
                            selected_ids.append(item)
                            selected_labels.append(str(instance))
                        except (ObjectDoesNotExist, ValueError, TypeError):
                            selected_ids.append(item)
                            selected_labels.append(str(item))
            else:
                if isinstance(value, Model):
                    selected_ids = [value.pk]
                    selected_labels = [str(value)]
                else:
                    # Fetch the model instance by ID
                    try:
                        instance = related_model_class.objects.get(pk=value)
                        selected_ids = [value]
                        selected_labels = [str(instance)]
                    except (ObjectDoesNotExist, ValueError, TypeError):
                        selected_ids = [value]
                        selected_labels = [str(value)]

        context['selected_value'] = selected_ids[0] if selected_ids else ''
        context['selected_label'] = selected_labels[0] if selected_labels else ''
        context['selected_ids_json'] = json.dumps([str(v) for v in selected_ids])
        context['selected_labels_json'] = json.dumps([str(v) for v in selected_labels])
        
        return context
