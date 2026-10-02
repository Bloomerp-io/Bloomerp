"""Route an incoming object according to grouped model filters."""

from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from pydantic import TypeAdapter

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.automation.results import RouteResult
from bloomerp.automation.schema import (
    WorkflowIOSchema,
    WorkflowInputRequirement,
    WorkflowValueType,
)
from bloomerp.filters.definition import Filters
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.parser import deserialize_filters
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.widgets.filter_widget import FilterWidget


_FILTERS_ADAPTER = TypeAdapter(Filters)


class ObjectIfConditionForm(BaseContentTypeForm):
    """Configure the model and the grouped filters used to route its objects."""

    refresh_on_input = True

    filters = forms.JSONField(required=False, initial=list, widget=forms.HiddenInput())

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Show the filter editor once a model has been selected."""
        super().__init__(*args, **kwargs)
        content_type_id = self.initial.get("content_type_id") or self.data.get("content_type_id")
        if content_type_id:
            self.fields["filters"].widget = FilterWidget(
                content_type=ContentType(pk=content_type_id),
                include_controls=False,
            )


class ObjectIfConditionExecutor(BaseExecutor):
    """Route an object by membership in the configured filtered queryset."""

    config_form = ObjectIfConditionForm
    output_ports = (
        WorkflowNodeOutputPort("true", "True", max_connections=None),
        WorkflowNodeOutputPort("false", "False", max_connections=None),
    )
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.OBJECT,
        label="A database object",
        description="The incoming object is checked against the configured filters.",
    )

    @classmethod
    def accepts_input_schema(
        cls,
        incoming_schema: WorkflowIOSchema | None,
        config: dict[str, Any] | None = None,
    ) -> bool:
        """Accept direct objects and objects wrapped by CRUD triggers."""
        return (
            incoming_schema is not None
            and incoming_schema.value_type == WorkflowValueType.OBJECT
            and any(
                field.path in {"id", "instance.id"}
                or (
                    field.path == "instance"
                    and any(child.path == "instance.id" for child in field.children)
                )
                for field in incoming_schema.fields
            )
        )

    @classmethod
    def get_output_schema(
        cls,
        config: dict[str, Any] | None = None,
        input_schema: WorkflowIOSchema | None = None,
        port_id: str = "default",
    ) -> WorkflowIOSchema | None:
        """Pass the incoming object schema through either output port."""
        return input_schema

    def execute(self, input_data: dict[str, Any]) -> RouteResult:
        """Route true only when the incoming object matches the saved filters."""
        params = self.resolve_config(input_data)
        model, _ = get_model_and_content_type_or_404(params.get("content_type_id"))
        filters = params.get("filters") or []
        if isinstance(filters, str):
            filters = deserialize_filters(filters)
        else:
            filters = _FILTERS_ADAPTER.validate_python(filters, strict=True)

        queryset = ModelFilterManager(model).apply(filters, queryset=model.objects.all())
        object_id = input_data.get("id")
        if object_id is None:
            instance = input_data.get("instance")
            object_id = instance.get("id") if isinstance(instance, dict) else getattr(instance, "pk", None)
        matches = object_id is not None and queryset.filter(pk=object_id).exists()
        return RouteResult(
            port_id="true" if matches else "false",
            output=input_data,
        )
