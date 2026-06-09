from dataclasses import field

from bloomerp.automation.triggers.base import BaseTrigger
from django import forms
from django.contrib.contenttypes.models import ContentType

from bloomerp.automation.utils import model_to_schema_field
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from django.db.utils import OperationalError, ProgrammingError
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
)


class ObjectCrudTriggerForm(forms.Form):
    content_type_id = forms.IntegerField(
        label="Model",
        widget=ForeignFieldWidget(
            attrs={
                "class" : "input w-full",
                "is_m2m": False,
            }
        ),
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


class ObjectCrudTrigger(BaseTrigger):
    config_form = ObjectCrudTriggerForm
    input_requirement = WorkflowInputRequirement(
        value_type="none",
        label="No input",
        description="Triggers start workflows and do not receive upstream input.",
    )
    output_schema = WorkflowIOSchema(
        value_type="object",
        label="Changed object",
        description="The object that created, updated, or deleted the workflow event.",
    )

    def execute(self, trigger_data:dict):
        instance = trigger_data.get("instance")
        fields = {}
        if instance is not None:
            fields = {
                field.name: getattr(instance, field.name)
                for field in instance._meta.fields
            }

        return {
            "event": trigger_data.get("event"),
            "instance": instance,
            "fields": fields,
            "data": trigger_data.get("data", {}),
        }

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
            value_type="object",
            label=str(model._meta.verbose_name).title(),
            description=f"The {model._meta.verbose_name} that triggered this workflow.",
            fields=[
                model_to_schema_field(model, path_prefix="instance"),
                WorkflowValueField(
                    path="event",
                    label="Event",
                    value_type="string",
                ),
                WorkflowValueField(
                    path="data",
                    label="Trigger Data",
                    value_type="object",
                )
            ],
        )

