from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.list_filter_widget import ListFilterWidget
from ..base_executor import BaseExecutor
from django.contrib.contenttypes.models import ContentType
from django import forms
from django.db.utils import OperationalError, ProgrammingError
import json
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    flatten_schema_fields,
    model_fields_to_value_fields,
)

class ConfigParamsForm(forms.Form):
    content_type_id = forms.IntegerField(
        widget=ForeignFieldWidget(
            {
                "class" : "input w-full",
                "is_m2m" : False,
            }            
        )
    )
    filter = forms.CharField(
        required=False,
        widget=ListFilterWidget()
    )
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            application_field = ApplicationField.objects.filter(
                field="content_type"
            ).first()
            self.fields["content_type_id"].widget.attrs.update(application_field.meta if application_field else {})
        except (OperationalError, ProgrammingError):
            self.fields["content_type_id"].widget.attrs.update({})

        content_type_id = None
        raw_content_type_id = self._get_field_value("content_type_id")
        if raw_content_type_id not in (None, ""):
            try:
                content_type_id = int(raw_content_type_id)
            except (TypeError, ValueError):
                content_type_id = None

        filter_widget = self.fields["filter"].widget
        if content_type_id is not None:
            filter_widget.attrs["related_model"] = content_type_id

        initial_filter = self._normalize_filter_value(self._get_field_value("filter"))
        if initial_filter is not None:
            self.initial["filter"] = initial_filter

    def _get_field_value(self, field_name: str):
        if self.is_bound:
            return self.data.get(self.add_prefix(field_name))
        return self.initial.get(field_name)

    def _normalize_filter_value(self, raw_value):
        if raw_value in (None, "", []):
            return None

        if isinstance(raw_value, str):
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                return None
        elif isinstance(raw_value, dict):
            parsed_value = raw_value
        else:
            return None

        field = parsed_value.get("field")
        operator = parsed_value.get("operator")
        if not field or not operator:
            return None

        application_field_id = parsed_value.get("applicationFieldId")
        content_type_id = self._get_field_value("content_type_id")
        if application_field_id in (None, ""):
            field_path = str(field).split("__")
            field_name = field_path[0] if field_path else None
            if field_name and content_type_id not in (None, ""):
                try:
                    application_field = ApplicationField.get_for_content_type_id(int(content_type_id)).filter(
                        field=field_name
                    ).first()
                except (TypeError, ValueError, OperationalError, ProgrammingError):
                    application_field = None
                if application_field is not None:
                    application_field_id = application_field.id

        return {
            "field": str(field),
            "applicationFieldId": str(application_field_id) if application_field_id not in (None, "") else None,
            "operator": str(operator),
            "value": parsed_value.get("value"),
            "key": parsed_value.get("key"),
        }
    

class ListObjectsExecutor(BaseExecutor):
    config_form = ConfigParamsForm
    input_requirement = WorkflowInputRequirement(
        kind="any",
        label="Any input",
        description="The incoming data is not used by this action.",
    )
    output_schema = WorkflowIOSchema(
        kind="list",
        label="Objects",
        description="A list of database objects.",
        fields=[
            WorkflowValueField("input", "Objects", "list"),
        ],
    )
    
    def execute(self, input_data: dict) -> list[dict]:
        # Get the content type id
        content_type_id = self.config.get("content_type_id")
        filter_config = self.config.get("filter")
        
        # Get the content type ID
        ModelCls = ContentType.objects.get(id=content_type_id).model_class()

        queryset = ModelCls.objects.all()
        if isinstance(filter_config, str):
            try:
                filter_config = json.loads(filter_config)
            except json.JSONDecodeError:
                filter_config = None

        if isinstance(filter_config, dict):
            field = filter_config.get("field")
            operator = filter_config.get("operator")
            value = filter_config.get("value")
            if field and operator and value not in (None, "", []):
                queryset = queryset.filter(**{f"{field}__{operator}": value})
        
        return [
            {
                field.name: field.value_from_object(obj)
                for field in ModelCls._meta.fields
            }
            for obj in queryset
        ]

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
    ) -> WorkflowIOSchema:
        content_type_id = (config or {}).get("parameters", {}).get("content_type_id")
        if not content_type_id:
            return cls.output_schema

        try:
            content_type = ContentType.objects.get(id=content_type_id)
        except (ContentType.DoesNotExist, ValueError, TypeError):
            return cls.output_schema

        model = content_type.model_class()
        if model is None:
            return cls.output_schema

        return WorkflowIOSchema(
            kind="list",
            label=str(model._meta.verbose_name_plural).title(),
            description=f"A list of {model._meta.verbose_name_plural}.",
            fields=[
                WorkflowValueField("input", f"{model._meta.verbose_name_plural.title()} List", "list"),
                *model_fields_to_value_fields(model, "input.0"),
            ],
        )

    
    
