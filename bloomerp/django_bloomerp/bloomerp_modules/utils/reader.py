from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml
from django.db import models
from django.db.models import Model

from bloomerp.field_types.types import FieldType, FieldTypeDefinition
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.modules.definition import FieldConfig, ModelConfig, ModuleConfig, module_registry


def _get_field_type_definition(field_type: str) -> FieldTypeDefinition:
    field_definition = FieldType.from_id(field_type).value
    if not field_definition.allow_in_model:
        raise ValueError(f"Field type '{field_type}' is not allowed for model creation.")
    if field_definition.model_field_cls is None:
        raise ValueError(f"Field type '{field_type}' has no Django field class mapping.")
    return field_definition


def _get_validator_functions(field_config: FieldConfig) -> list[Callable]:
    validator_functions = []
    for validator_path in field_config.validators:
        try:
            module_path, function_name = validator_path.rsplit(".", 1)
            validator_module = __import__(module_path, fromlist=[function_name])
            validator_functions.append(getattr(validator_module, function_name))
        except (ImportError, AttributeError) as exc:
            print(f"Warning: Could not import validator '{validator_path}': {exc}")
    return validator_functions


def _get_callable(path: str) -> Callable:
    module_path, callable_name = path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[callable_name])
    return getattr(module, callable_name)


def _convert_string_to_callable(field_opts: dict) -> dict:
    updated_opts = {}
    for field, value in field_opts.items():
        if field == "on_delete" and isinstance(value, str) and hasattr(models, value):
            updated_opts[field] = getattr(models, value)
            continue

        if isinstance(value, str) and value.startswith("call(") and value.endswith(")"):
            callable_path = value[5:-1]
            try:
                updated_opts[field] = _get_callable(callable_path)
            except (ImportError, AttributeError, ValueError) as exc:
                print(f"Warning: Could not call '{callable_path}': {exc}")
                updated_opts[field] = value
            continue

        updated_opts[field] = value
    return updated_opts


def get_model_class_name(model_name: str) -> str:
    return "".join(word.capitalize() for word in model_name.replace("-", " ").replace("_", " ").split())


def _normalize_layout_item(raw_item: Any) -> LayoutItem | None:
    if isinstance(raw_item, dict):
        item_id = raw_item.get("id")
        if item_id in (None, ""):
            return None
        return LayoutItem(id=item_id, colspan=raw_item.get("colspan", 1))

    if raw_item in (None, ""):
        return None

    return LayoutItem(id=raw_item, colspan=1)


def _normalize_field_layout(field_layout: Any) -> FieldLayout | None:
    if isinstance(field_layout, FieldLayout):
        return field_layout if field_layout.rows else None

    if field_layout in (None, {}):
        return None

    raw_rows = None
    if isinstance(field_layout, dict):
        if isinstance(field_layout.get("rows"), list):
            raw_rows = field_layout.get("rows", [])
        elif isinstance(field_layout.get("sections"), list):
            raw_rows = field_layout.get("sections", [])
    elif isinstance(field_layout, list):
        raw_rows = field_layout

    if not isinstance(raw_rows, list):
        return None

    rows: list[LayoutRow] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue

        raw_items = raw_row.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        items = []
        for raw_item in raw_items:
            item = _normalize_layout_item(raw_item)
            if item is not None:
                items.append(item)

        rows.append(
            LayoutRow(
                title=raw_row.get("title"),
                columns=raw_row.get("columns", 1),
                items=items,
            )
        )

    return FieldLayout(rows=rows) if rows else None


def create_model_from_config(
    model_config: ModelConfig,
    module_config: ModuleConfig,
    model_lookup: dict[str, str] | None = None,
) -> type[Model]:
    attrs = {}

    for field_config in model_config.fields:
        field_definition = _get_field_type_definition(field_config.type)
        field_class = field_definition.model_field_cls
        default_opts = dict(field_definition.default_model_field_args)
        validator_functions = _get_validator_functions(field_config)

        field_opts = {
            "help_text": field_config.description,
            "verbose_name": field_config.name,
            **default_opts,
        }

        if validator_functions:
            field_opts["validators"] = validator_functions

        if field_config.options:
            for key, value in field_config.options.items():
                if key is None:
                    field_opts["null"] = value
                else:
                    field_opts[key] = value

        if "to" in field_opts and isinstance(field_opts["to"], str):
            to_ref = field_opts["to"]
            if model_lookup and to_ref in model_lookup:
                field_opts["to"] = f"bloomerp_modules.{model_lookup[to_ref]}"

        field_opts = _convert_string_to_callable(field_opts)
        attrs[field_config.id] = field_class(**field_opts)

    class Meta:
        verbose_name = model_config.name
        db_table = f"{(module_config.full_id or module_config.id).replace('.', '_')}_{model_config.id}"
        if model_config.name_plural:
            verbose_name_plural = model_config.name_plural
        if model_config.custom_permissions:
            permissions = [(perm.id, perm.name) for perm in model_config.custom_permissions]

    config = BloomerpModelConfig(
        module=module_config.full_id or module_config.id,
        layout=_normalize_field_layout(getattr(model_config, "field_layout", None)),
        record_activity_log=True
    )

    attrs["Meta"] = Meta
    attrs["__module__"] = "bloomerp_modules.models"
    attrs["bloomerp_config"] = config

    model_class_name = get_model_class_name(model_config.name)

    if model_config.string_representation:
        def __str__(self):
            try:
                values = {field.id: getattr(self, field.id) for field in model_config.fields}
                return model_config.string_representation.format(**values)
            except Exception as exc:
                return f"<{model_class_name} (error in __str__: {exc})>"

        attrs["__str__"] = __str__

    if hasattr(model_config, "has_avatar") and model_config.has_avatar is False:
        attrs["avatar"] = None

    from bloomerp.models.base_bloomerp_model import BloomerpModel

    return type(model_class_name, (BloomerpModel,), attrs)


def _load_yaml(path: Path) -> dict[str, Any] | None:
    with path.open("r") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        return None
    return data


def _load_model_configs(module_dir: Path) -> list[ModelConfig]:
    models: list[ModelConfig] = []
    for model_file in sorted(module_dir.glob("*.yaml")):
        if model_file.name == "config.yaml":
            continue

        model_data = _load_yaml(model_file)
        if not model_data:
            continue

        clean_model_data = {
            "id": model_data.get("id", model_file.stem),
            "name": model_data.get("name", model_file.stem.replace("_", " ").title()),
            "description": model_data.get("description", ""),
            "enabled": model_data.get("enabled", True),
            "fields": model_data.get("fields", []),
            "name_plural": model_data.get("name_plural"),
            "custom_permissions": model_data.get("custom_permissions") or [],
            "string_representation": model_data.get("string_representation"),
            "field_layout": _normalize_field_layout(model_data.get("field_layout")),
        }

        try:
            models.append(ModelConfig(**clean_model_data))
        except Exception as exc:
            print(f"Error loading model from {model_file}: {exc}")

    return models


def _scan_module_tree(module_dir: Path, parent_module_id: str | None = None) -> list[ModuleConfig]:
    config_path = module_dir / "config.yaml"
    if not config_path.exists():
        return []

    module_data = _load_yaml(config_path)
    if not module_data:
        return []

    module_id = module_data.get("id", module_dir.name)
    full_id = f"{parent_module_id}.{module_id}" if parent_module_id else module_id

    module = ModuleConfig(
        id=module_id,
        name=module_data.get("name", module_dir.name.replace("_", " ").title()),
        code=module_data.get("code", module_dir.name.upper()),
        description=module_data.get("description", ""),
        enabled=module_data.get("enabled", True),
        icon=module_data.get("icon", "fa-solid fa-folder"),
        parent_module_id=module_data.get("parent_module_id", parent_module_id),
        full_id=full_id,
        visible=module_data.get("visible", True),
    )

    modules = [module]
    for child_dir in sorted(item for item in module_dir.iterdir() if item.is_dir()):
        modules.extend(_scan_module_tree(child_dir, full_id))
    return modules


def scan_modules_directory() -> list[ModuleConfig]:
    modules_dir = Path(__file__).parent.parent / "modules"
    modules: list[ModuleConfig] = []
    if not modules_dir.exists():
        return modules

    for module_dir in sorted(item for item in modules_dir.iterdir() if item.is_dir()):
        modules.extend(_scan_module_tree(module_dir))

    return modules


def load_all_models_from_modules() -> dict[str, type[Model]]:
    modules = scan_modules_directory()
    for module in modules:
        module_registry.register(module)
    module_registry._rebuild_hierarchy_metadata()

    models_dir = Path(__file__).parent.parent / "modules"
    model_lookup: dict[str, str] = {}
    ordered_modules = [module_registry.get(module.full_id or module.id) for module in modules]
    ordered_modules = [module for module in ordered_modules if module is not None]

    for module in ordered_modules:
        module_dir = models_dir / Path(str(module.route_path or module.id))
        for model_config in _load_model_configs(module_dir):
            module_key = module.full_id or module.id
            model_lookup[f"{module_key}.{model_config.id}"] = get_model_class_name(model_config.name)

    dynamic_models: dict[str, type[Model]] = {}
    for module in ordered_modules:
        module_dir = models_dir / Path(str(module.route_path or module.id))
        for model_config in _load_model_configs(module_dir):
            try:
                model_class = create_model_from_config(model_config, module, model_lookup)
            except Exception as exc:
                module_key = module.full_id or module.id
                print(f"Error creating model '{model_config.name}' from module '{module_key}': {exc}")
                continue
            module_key = (module.full_id or module.id).replace(".", "_")
            dynamic_models[f"{module_key}_{model_config.id}"] = model_class

    return dynamic_models


def parse_yaml_config(yaml_file_path: str) -> ModuleConfig:
    data = _load_yaml(Path(yaml_file_path))
    if not data or "module" not in data:
        raise ValueError(f"Invalid module YAML file: {yaml_file_path}")

    module_data = data["module"]
    return ModuleConfig(
        id=module_data["id"],
        name=module_data["name"],
        code=module_data["code"],
        description=module_data.get("description"),
        icon=module_data.get("icon", "fa-solid fa-folder"),
        parent_module_id=module_data.get("parent_module_id"),
        visible=module_data.get("visible", True),
    )
