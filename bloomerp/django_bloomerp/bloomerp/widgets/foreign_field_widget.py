import json
from typing import Optional
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.forms import widgets
from django.db.models import Model
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse


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

    def get_object_detail_url(self, obj) -> str:
        if hasattr(obj, "get_absolute_url"):
            try:
                return obj.get_absolute_url()
            except Exception:
                pass
        if hasattr(obj, "pk") and hasattr(obj, "__class__"):
            try:
                from bloomerp.utils.models import get_detail_view_url
                return reverse(get_detail_view_url(obj.__class__), kwargs={"pk": obj.pk})
            except Exception:
                return ""
        return ""

    def value_from_datadict(self, data, files, name):
        if self.is_m2m and hasattr(data, "getlist"):
            return [value for value in data.getlist(name) if value not in (None, "")]
        return super().value_from_datadict(data, files, name)

    def _is_empty_value(self, value) -> bool:
        if value in (None, ""):
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, (list, tuple, set)) and len(value) == 0:
            return True
        return False

    def _normalize_related_pk(self, value):
        if self._is_empty_value(value):
            return None

        if isinstance(value, Model) or hasattr(value, "pk"):
            return getattr(value, "pk", value)

        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            return value

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None

            try:
                return UUID(stripped)
            except (ValueError, TypeError, AttributeError):
                pass

            if stripped.endswith(".0"):
                integer_candidate = stripped[:-2]
                if integer_candidate.lstrip("-").isdigit():
                    return integer_candidate

            return stripped

        return value

    def get_context(self, name, value:Model, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["is_m2m"] = self.is_m2m
        context["content_type_id"] = self.get_related_content_type_id() or ""

        # Check if an invalid entry was made
        if (attrs or {}).get('aria-invalid', 'false') == 'true':
            context['invalid'] = True
        
        # Get the related model class
        related_model_class = self.get_related_model_class()
        
        # Set selected value(s)
        selected_ids = []
        selected_labels = []
        selected_urls = []

        if not self._is_empty_value(value):
            if self.is_m2m:
                if hasattr(value, 'all'):
                    items = list(value.all())
                elif isinstance(value, (list, tuple, set)):
                    items = list(value)
                else:
                    items = [value]

                for item in items:
                    normalized_item = self._normalize_related_pk(item)
                    if normalized_item is None:
                        continue
                    if isinstance(item, Model) or hasattr(item, "pk"):
                        selected_ids.append(item.pk)
                        selected_labels.append(str(item))
                        selected_urls.append(self.get_object_detail_url(item))
                    elif related_model_class is not None:
                        # Fetch the model instance by ID
                        try:
                            instance = related_model_class.objects.get(pk=normalized_item)
                            selected_ids.append(str(instance.pk))
                            selected_labels.append(str(instance))
                            selected_urls.append(self.get_object_detail_url(instance))
                        except (ObjectDoesNotExist, ValueError, TypeError):
                            selected_ids.append(str(normalized_item))
                            selected_labels.append(str(normalized_item))
                            selected_urls.append("")
                    else:
                        selected_ids.append(str(normalized_item))
                        selected_labels.append(str(normalized_item))
                        selected_urls.append("")
            else:
                if isinstance(value, Model) or hasattr(value, "pk"):
                    selected_ids = [str(value.pk)]
                    selected_labels = [str(value)]
                    selected_urls = [self.get_object_detail_url(value)]
                elif related_model_class is not None:
                    normalized_value = self._normalize_related_pk(value)
                    if normalized_value is None:
                        normalized_value = ""
                    # Fetch the model instance by ID
                    try:
                        instance = related_model_class.objects.get(pk=normalized_value)
                        selected_ids = [str(instance.pk)]
                        selected_labels = [str(instance)]
                        selected_urls = [self.get_object_detail_url(instance)]
                    except (ObjectDoesNotExist, ValueError, TypeError):
                        if normalized_value not in ("", None):
                            selected_ids = [str(normalized_value)]
                            selected_labels = [str(normalized_value)]
                            selected_urls = [""]
                else:
                    normalized_value = self._normalize_related_pk(value)
                    if normalized_value not in ("", None):
                        selected_ids = [str(normalized_value)]
                        selected_labels = [str(normalized_value)]
                        selected_urls = [""]

        context['selected_value'] = selected_ids[0] if selected_ids else ''
        context['selected_label'] = selected_labels[0] if selected_labels else ''
        context['selected_ids_json'] = json.dumps([str(v) for v in selected_ids])
        context['selected_labels_json'] = json.dumps([str(v) for v in selected_labels])
        context['selected_urls_json'] = json.dumps(selected_urls)
        
        return context
