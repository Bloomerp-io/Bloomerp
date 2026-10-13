from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.ports import DEFAULT_OUTPUT_PORT
from django import forms

from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY, WorkflowNodeDefinition
from bloomerp.mcp.definition import McpResource
from bloomerp.models.automation.workflow import Workflow
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.mcp.authoring_references import literal_metadata, packaged_guide, sensitive_name
from django.core.exceptions import PermissionDenied

from django.http import HttpRequest


from typing import Any


def field_reference(name: str, field: forms.Field) -> dict[str, Any]:
    """Describe declared validation and static choices while omitting sensitive defaults."""
    result: dict[str, Any] = {
        "name": name,
        "form_field_type": type(field).__name__,
        "label": str(field.label or name.replace("_", " ").title()),
        "required": field.required,
        "help_text": str(field.help_text),
        "widget_type": type(field.widget).__name__,
        "hidden": field.widget.is_hidden,
    }
    sensitive = isinstance(field.widget, forms.PasswordInput) or sensitive_name(name)
    if sensitive:
        result["default_status"] = "omitted_sensitive"
    elif callable(field.initial):
        result["default_status"] = "dynamic_not_evaluated"
    else:
        result["initial"] = literal_metadata(field.initial)
        result["default_status"] = "form_initial_not_runtime_default"
    for attribute in (
        "min_value",
        "max_value",
        "min_length",
        "max_length",
        "max_digits",
        "decimal_places",
    ):
        value = getattr(field, attribute, None)
        if value is not None:
            result[attribute] = literal_metadata(value)
    if sensitive:
        result["choices_status"] = "omitted_sensitive"
        return result
    # Do not iterate ModelChoiceIterator, CallableChoiceIterator or lazy providers.
    choices = getattr(field, "choices", None)
    if choices is None:
        choices = getattr(field.widget, "choices", None)
    if isinstance(field, forms.ModelChoiceField):
        result["choices_status"] = "user_scoped_not_enumerated"
    elif type(choices) in (list, tuple):
        result["choices"] = literal_metadata(choices)
        result["choices_status"] = "declared_static"
    elif choices is not None:
        result["choices_status"] = "dynamic_not_evaluated"
    if hasattr(field.widget, "model"):
        model = field.widget.model
        if isinstance(model, type) and hasattr(model, "_meta"):
            result["related_model"] = model._meta.label
        result["choices_status"] = "user_scoped_not_enumerated"
    return result


def node_reference(definition: WorkflowNodeDefinition) -> dict[str, Any]:
    """Read class declarations without constructing a form, executor or workflow."""
    result: dict[str, Any] = {
        "sub_type": definition.id,
        "type": definition.type,
        "name": str(definition.name),
        "description": str(definition.description),
        "parameters": [],
    }
    executor = definition.executor_cls
    if executor is None:
        result["configuration_status"] = "no_executor_declared"
        return result
    form_class = executor.config_form
    if isinstance(form_class, type) and issubclass(form_class, forms.BaseForm):
        result["parameters"] = [
            field_reference(name, field)
            for name, field in form_class.base_fields.items()
        ]
        result["configuration_form"] = (
            f"{form_class.__module__}.{form_class.__qualname__}"
        )
        result["configuration_status"] = "declared_fields_only"
    else:
        result["configuration_status"] = "no_declarative_form_available"
    result["input_requirement"] = executor.input_requirement.to_dict()
    result["output_schema"] = executor.output_schema.to_dict()
    result["output_ports"] = [
        port.to_dict() for port in (executor.output_ports or (DEFAULT_OUTPUT_PORT,))
    ]
    result["schema_status"] = (
        "declared_baseline; configuration-specific schema and ports may differ"
    )
    result["metadata_factory_overrides"] = [
        method_name
        for method_name in (
            "get_config_form",
            "get_input_requirement",
            "get_output_schema",
            "get_output_ports",
        )
        if getattr(getattr(executor, method_name), "__func__", None)
        is not getattr(BaseExecutor, method_name).__func__
    ]
    return result


@router.register(
    name="Workflow authoring reference",
    description="Workflow payloads, connections and all installed node configuration forms.",
    mcp=McpResource(
        uri="bloomerp://guides/create-workflow", mime_type="application/json"
    ),
)
def workflow_resource(request: HttpRequest) -> dict[str, Any]:
    """Return the live node registry and a safe workflow construction guide."""
    policy_manager = UserPolicyManager(request.user)
    if not policy_manager.has_global_permission(
        Workflow,
        [BloomerpPermission.VIEW]
    ):
        raise PermissionDenied(
            "Access to workflows is required to view this resource."
        )
    
    return {
        "guide": packaged_guide("create-workflow.md"),
        "nodes": [
            node_reference(definition) for definition in WORKFLOW_NODE_REGISTRY.values()
        ],
        "metadata_limits": (
            "Form initial values are editor suggestions, not guaranteed runtime defaults. "
            "Form constructors, callable defaults and dynamic/model choices are never evaluated. "
            "Fields added during form initialization and configured IO schemas require the authenticated editor. "
            "No saved workflow configuration, credentials or object choices are read."
        ),
    }