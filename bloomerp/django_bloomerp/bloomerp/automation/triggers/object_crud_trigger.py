from dataclasses import replace
from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db.utils import OperationalError, ProgrammingError

from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
)
from bloomerp.automation.triggers.base import BaseTrigger
from bloomerp.automation.utils import model_to_schema_field
from bloomerp.models.application_field import ApplicationField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class ObjectCrudTriggerForm(forms.Form):
    content_type_id = forms.IntegerField(
        label="Model",
        widget=ForeignFieldWidget(
            attrs={
                "class": "input w-full",
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
            self.fields["content_type_id"].widget.attrs.update(
                application_field.meta if application_field else {}
            )
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
        description="The workflow event wraps the changed object in instance; object fields are not top-level input fields.",
        fields=[
            WorkflowValueField(
                path="instance",
                label="Instance",
                value_type="object",
                description="The changed model instance. Access its fields through input.instance.<field>; available fields depend on the selected model.",
            ),
            WorkflowValueField(
                path="event",
                label="Event",
                value_type="string",
                description="The object event that triggered the workflow.",
            ),
            WorkflowValueField(
                path="fields",
                label="Fields",
                value_type="object",
                description="A snapshot of the model's concrete field values, accessed through input.fields.<field>.",
            ),
            WorkflowValueField(
                path="data",
                label="Trigger Data",
                value_type="object",
                description="Additional trigger data; its contents depend on the event source.",
            ),
        ],
    )

    def execute(self, trigger_data: dict[str, Any]) -> dict[str, Any]:
        """Wrap the changed instance, concrete field values and event data for downstream nodes."""
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
        config: dict[str, Any] | None = None,
        input_schema: WorkflowIOSchema | None = None,
        port_id: str = "default",
    ) -> WorkflowIOSchema:
        """Enrich the declared event wrapper with fields from the configured model."""
        content_type_id = (config or {}).get("content_type_id")
        if not content_type_id:
            return cls.output_schema

        try:
            content_type = ContentType.objects.get(id=content_type_id)
        except (ContentType.DoesNotExist, ValueError, TypeError):
            return cls.output_schema

        model = content_type.model_class()
        if model is None:
            return cls.output_schema

        instance_field = model_to_schema_field(model, path_prefix="instance")
        return replace(
            cls.output_schema,
            label=str(model._meta.verbose_name).title(),
            description=f"The {model._meta.verbose_name} is available inside input.instance; event, fields and data describe the triggering event.",
            fields=[
                replace(value_field, children=instance_field.children)
                if value_field.path == "instance"
                else value_field
                for value_field in cls.output_schema.fields
            ],
        )
