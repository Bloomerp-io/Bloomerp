from bloomerp.automation.schema import WorkflowValueField, WorkflowValueType
from django.db import models
from typing import Any


def get_parameters_from_config(config: dict|None) -> dict:
    """Utility function to extract parameters from a config dictionary."""
    if config is None:
        return {}
    
    parameters = config.get("parameters", {})
    if isinstance(parameters, dict):
        return parameters
    return {}

def field_type_for_django_field(field: models.Field) -> WorkflowValueType:
    if isinstance(field, (models.EmailField, models.CharField, models.TextField, models.SlugField, models.URLField)):
        return WorkflowValueType.STRING
    if isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
        return WorkflowValueType.NUMBER
    if isinstance(field, models.BooleanField):
        return WorkflowValueType.BOOLEAN
    if isinstance(field, (models.DateField, models.DateTimeField, models.TimeField)):
        return WorkflowValueType.DATETIME
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return WorkflowValueType.OBJECT
    return WorkflowValueType.UNKNOWN


def model_fields_to_value_fields(
    model: type[models.Model],
    path_prefix: str,
) -> list[WorkflowValueField]:
    return [
        WorkflowValueField(
            path=f"{path_prefix}.{field.name}",
            label=str(field.verbose_name).title(),
            value_type=field_type_for_django_field(field),
        )
        for field in model._meta.fields
    ]


def model_to_schema_field(
    model: type[models.Model],
    path_prefix: str = "instance",
    label="Instance",
    optional: bool = False,
) -> WorkflowValueField:
    """Convert a Django model to a WorkflowValueField schema."""
    return WorkflowValueField(
        path=path_prefix,
        label=label,
        value_type=WorkflowValueType.OBJECT,
        children=model_fields_to_value_fields(model, path_prefix),
        optional=optional
    )


def _value_type_for_json(value: Any) -> str:
    if isinstance(value, bool):
        return WorkflowValueType.BOOLEAN.value
    if isinstance(value, (int, float)):
        return WorkflowValueType.NUMBER.value
    if isinstance(value, str):
        return WorkflowValueType.STRING.value
    if isinstance(value, list):
        return WorkflowValueType.LIST.value
    if isinstance(value, dict):
        return WorkflowValueType.OBJECT.value
    return WorkflowValueType.UNKNOWN.value


def json_to_type_and_fields(obj: Any, path: str = "") -> tuple[WorkflowValueType, list[WorkflowValueField]]:
    if isinstance(obj, list):
        if len(obj) == 0:
            return WorkflowValueType.LIST, []

        list_item = obj[0]
        if not isinstance(list_item, (dict, list)):
            return WorkflowValueType.LIST, []

        child_path = f"{path}.0" if path else "0"
        _, fields = json_to_type_and_fields(list_item, child_path)
        return WorkflowValueType.LIST, fields

    if not isinstance(obj, dict):
        return _value_type_for_json(obj), []

    fields: list[WorkflowValueField] = []
    for key, value in obj.items():
        field_path = key if not path else f"{path}.{key}"
        _, children = json_to_type_and_fields(value, field_path)
        fields.append(
            WorkflowValueField(
                path=field_path,
                label=key.replace("_", " ").title(),
                value_type=_value_type_for_json(value),
                children=children,
            )
        )

    return WorkflowValueType.OBJECT, fields


def enhanced_get_attr(obj:Any, attr:str, default:Any=None) -> Any:
    """Enhanced getattr that supports nested attribute access using dot notation."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)