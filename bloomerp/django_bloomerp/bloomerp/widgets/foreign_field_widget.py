import json
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.forms import widgets
from django.db.models import Model
from django.core.exceptions import ObjectDoesNotExist


class ForeignFieldWidget(widgets.Widget):
    template_name = 'widgets/foreign_field_widget.html'
    is_m2m: bool = False

    def __init__(self, model=None, attrs=None):
        if attrs is None and isinstance(model, dict):
            attrs = model
            model = None

        attrs = attrs.copy() if attrs else {}
        self.is_m2m = attrs.pop('is_m2m', False)
        self.model = attrs.pop('model', model)
        super().__init__(attrs)

    def get_related_content_type_id(self) -> Optional[int]:
        related_model_id = self.attrs.get('related_model')
        if related_model_id not in (None, ''):
            try:
                return int(related_model_id)
            except (TypeError, ValueError):
                return None

        if self.model is not None:
            return ContentType.objects.get_for_model(self.model).pk

        return None

    def get_related_model_class(self):
        content_type_id = self.get_related_content_type_id()
        if content_type_id is not None:
            try:
                return ContentType.objects.get(pk=content_type_id).model_class()
            except ContentType.DoesNotExist:
                return None

        return self.model

    def get_context(self, name, value:Model, attrs):
        context = super().get_context(name, value, attrs)
        context["content_type_id"] = self.get_related_content_type_id() or ""

        # Check if an invalid entry was made
        if (attrs or {}).get('aria-invalid', 'false') == 'true':
            context['invalid'] = True
        
        # Get the related model class
        related_model_class = self.get_related_model_class()
        
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
                    elif related_model_class is not None:
                        # Fetch the model instance by ID
                        try:
                            instance = related_model_class.objects.get(pk=item)
                            selected_ids.append(item)
                            selected_labels.append(str(instance))
                        except (ObjectDoesNotExist, ValueError, TypeError):
                            selected_ids.append(item)
                            selected_labels.append(str(item))
                    else:
                        selected_ids.append(item)
                        selected_labels.append(str(item))
            else:
                if isinstance(value, Model):
                    selected_ids = [value.pk]
                    selected_labels = [str(value)]
                elif related_model_class is not None:
                    # Fetch the model instance by ID
                    try:
                        instance = related_model_class.objects.get(pk=value)
                        selected_ids = [value]
                        selected_labels = [str(instance)]
                    except (ObjectDoesNotExist, ValueError, TypeError):
                        selected_ids = [value]
                        selected_labels = [str(value)]
                else:
                    selected_ids = [value]
                    selected_labels = [str(value)]

        context['selected_value'] = selected_ids[0] if selected_ids else ''
        context['selected_label'] = selected_labels[0] if selected_labels else ''
        context['selected_ids_json'] = json.dumps([str(v) for v in selected_ids])
        context['selected_labels_json'] = json.dumps([str(v) for v in selected_labels])
        
        return context
