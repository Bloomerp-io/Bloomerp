import json
from urllib.parse import urlencode

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.urls import reverse


class ListFilterWidget(forms.Widget):
    template_name = "widgets/list_filter_widget.html"

    def __init__(self, model=None, attrs=None):
        if attrs is None and isinstance(model, dict):
            attrs = model
            model = None

        attrs = attrs.copy() if attrs else {}
        self.model = attrs.pop("model", model)
        super().__init__(attrs)

    def get_related_content_type_id(self, attrs=None) -> int | None:
        merged_attrs = (self.attrs or {}).copy()
        if attrs:
            merged_attrs.update(attrs)

        related_model_id = merged_attrs.get("related_model")
        if related_model_id not in (None, ""):
            try:
                return int(related_model_id)
            except (TypeError, ValueError):
                return None

        if self.model is not None:
            try:
                return ContentType.objects.get_for_model(self.model).pk
            except Exception:
                return None

        return None

    def _normalize_initial_value(self, value) -> dict | None:
        if value in (None, "", []):
            return None

        if isinstance(value, str):
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                return None
        else:
            parsed_value = value

        if not isinstance(parsed_value, dict):
            return None

        field = parsed_value.get("field")
        operator = parsed_value.get("operator")
        if not field or not operator:
            return None

        normalized_value = parsed_value.get("value")
        if isinstance(normalized_value, Model) or hasattr(normalized_value, "pk"):
            normalized_value = str(getattr(normalized_value, "pk", normalized_value))
        elif isinstance(normalized_value, (list, tuple, set)):
            normalized_value = [str(item) for item in normalized_value if item not in (None, "")]
        elif normalized_value not in (None, ""):
            normalized_value = str(normalized_value)

        return {
            "field": str(field),
            "applicationFieldId": str(parsed_value.get("applicationFieldId")) if parsed_value.get("applicationFieldId") not in (None, "") else None,
            "operator": str(operator),
            "value": normalized_value,
            "key": str(parsed_value.get("key")) if parsed_value.get("key") not in (None, "") else None,
        }
    
    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)

        content_type_id = self.get_related_content_type_id(attrs)
        initial_filter = self._normalize_initial_value(value)
        query_string = urlencode({"initial_filter": json.dumps(initial_filter)}) if initial_filter else ""
        base_url = (
            reverse("components_filters_init", kwargs={"content_type_id": content_type_id})
            if content_type_id
            else ""
        )

        ctx["content_type_id"] = content_type_id or ""
        ctx["initial_filter_json"] = json.dumps(initial_filter) if initial_filter else ""
        ctx["url"] = (
            f"{base_url}?{query_string}" if query_string else base_url
        )
        return ctx