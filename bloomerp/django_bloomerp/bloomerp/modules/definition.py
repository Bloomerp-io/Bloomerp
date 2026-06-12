from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any

from django import apps
from django.db.models import Model
from pydantic import BaseModel, Field

from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.models.definition import BloomerpModelConfig

logger = logging.getLogger(__name__)


class BaseConfig(BaseModel):
    id: str
    name: str
    description: str | None = None
    enabled: bool = True


class FieldConfig(BaseConfig):
    type: str
    options: dict | None = None
    validators: list[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    id: str
    name: str


class ModelConfig(BaseConfig):
    name_plural: str | None = None
    fields: list[FieldConfig] = Field(default_factory=list)
    custom_permissions: list[PermissionConfig] = Field(default_factory=list)
    string_representation: str | None = None
    field_layout: FieldLayout | None = None


class ModuleConfig(BaseConfig):
    code: str 
    icon: str = "fa-solid fa-folder"
    parent_module_id: str | None = None
    visible: bool = True
    full_id: str | None = None
    route_path: str | None = None
    root_module_id: str | None = None
    depth: int = 0


class BloomerpModule:
    """Django-style authoring surface for Python module definitions."""

    id: str | None = None
    name: str | None = None
    code: str | None = None
    description: str | None = None
    enabled: bool = True
    icon: str = "fa-solid fa-folder"
    parent_module_id: str | None = None
    parent: str | None = None
    visible: bool = True
    route_path: str | None = None

    @classmethod
    def to_config(cls) -> ModuleConfig:
        data = {
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "enabled": cls.enabled,
            "icon": cls.icon,
            "visible": cls.visible,
            "route_path": cls.route_path,
        }

        parent_module_id = cls.parent_module_id or cls.parent
        if parent_module_id is not None:
            data["parent_module_id"] = parent_module_id

        data["code"] = cls.code or (cls.id.upper() if cls.id else None)
        return ModuleConfig(**data)


class ModuleRegistry:
    def __init__(self):
        self.items: dict[str, ModuleConfig] = {}
        self._module_models: dict[str, dict[str, type[Model]]] = {}

    def register(self, module: ModuleConfig) -> None:
        module_key = module.full_id or module.id
        if module_key in self.items:
            logger.warning("Module with ID '%s' already exists. Overwriting.", module_key)
        self.items[module_key] = module

    def get(self, module_id: str | None) -> ModuleConfig | None:
        if not module_id:
            return None
        return self.items.get(module_id)

    def get_all(self) -> dict[str, ModuleConfig]:
        return self.items.copy()

    def get_enabled(self) -> dict[str, ModuleConfig]:
        return {
            module_id: module
            for module_id, module in self.items.items()
            if module.enabled
        }

    def get_root_modules(self) -> list[ModuleConfig]:
        return [
            module
            for module in self.items.values()
            if module.parent_module_id is None
        ]

    def get_children(self, module_id: str | None) -> list[ModuleConfig]:
        if module_id is None:
            return self.get_root_modules()
        return [
            module
            for module in self.items.values()
            if module.parent_module_id == module_id
        ]

    def get_ancestors(self, module_id: str | None) -> list[ModuleConfig]:
        ancestors: list[ModuleConfig] = []
        current = self.get(module_id)
        seen: set[str] = set()
        while current and current.parent_module_id:
            if current.parent_module_id in seen:
                logger.warning("Detected circular module ancestry while resolving '%s'.", module_id)
                break
            seen.add(current.parent_module_id)
            parent = self.get(current.parent_module_id)
            if not parent:
                break
            ancestors.append(parent)
            current = parent
        ancestors.reverse()
        return ancestors

    def get_lineage(self, module_id: str | None) -> list[ModuleConfig]:
        module = self.get(module_id)
        if not module:
            return []
        return [*self.get_ancestors(module_id), module]

    def get_root(self, module_id: str | None) -> ModuleConfig | None:
        lineage = self.get_lineage(module_id)
        if not lineage:
            return None
        return lineage[0]

    def get_models_for_module(self, module_id: str, include_descendants: bool = False) -> list[type[Model]]:
        module_ids = {module_id}
        if include_descendants:
            module_ids.update(self._collect_descendant_ids(module_id))

        models: dict[str, type[Model]] = {}
        for current_id in module_ids:
            for model_key, model in self._module_models.get(current_id, {}).items():
                models.setdefault(model_key, model)
        return list(models.values())

    def get_module_for_model(self, model: type[Model]) -> ModuleConfig | None:
        config = self._get_model_config(model)
        if config and config.module:
            return self.get(config.module)

        model_key = model._meta.label_lower
        for module_id, models in self._module_models.items():
            if model_key in models:
                return self.get(module_id)
        return None

    def refresh(self) -> None:
        self.clear()

        for app_config in apps.apps.get_app_configs():
            try:
                module_package = importlib.import_module(f"{app_config.name}.modules")
            except ModuleNotFoundError:
                continue

            for _, attribute in inspect.getmembers(module_package, inspect.isclass):
                self._register_module_class(attribute, source=app_config.name)

            if not hasattr(module_package, "__path__"):
                continue

            for _, module_name, _ in pkgutil.iter_modules(module_package.__path__, module_package.__name__ + "."):
                if module_name.endswith(".definition"):
                    continue
                try:
                    imported_module = importlib.import_module(module_name)
                except Exception as exc:
                    logger.error("Error importing module '%s': %s", module_name, exc)
                    continue

                for _, attribute in inspect.getmembers(imported_module, inspect.isclass):
                    self._register_module_class(attribute, source=module_name)

        try:
            from bloomerp_modules.utils.reader import scan_modules_directory
        except Exception:
            scan_modules_directory = None

        if scan_modules_directory is not None:
            try:
                for module in scan_modules_directory():
                    self.register(module)
            except Exception as exc:
                logger.error("Error loading YAML module definitions: %s", exc)

        self._rebuild_hierarchy_metadata()
        self._register_models_from_apps()

    def clear(self) -> None:
        self.items.clear()
        self._module_models.clear()

    def __len__(self) -> int:
        return len(self.items)

    def __contains__(self, module_id: str) -> bool:
        return module_id in self.items

    def _register_models_from_apps(self) -> None:
        self._module_models.clear()
        for model in apps.apps.get_models():
            config = self._get_model_config(model)
            module_id = None
            if config and config.module:
                module_id = config.module
            if not module_id:
                module_id = "misc"

            module = self.get(module_id)
            if module is None:
                module = ModuleConfig(
                    id=module_id.split(".")[-1],
                    name=module_id.split(".")[-1].replace("_", " ").replace("-", " ").title(),
                    code=module_id.split(".")[-1],
                    full_id=module_id,
                )
                self.register(module)
                self._rebuild_hierarchy_metadata()

            self._add_model_to_module(module, model)

    def _get_model_config(self, model: type[Model]) -> BloomerpModelConfig | None:
        config = getattr(model, "bloomerp_config", None)
        if isinstance(config, BloomerpModelConfig):
            return config
        return None

    def _register_module_class(self, attribute: type, source: str) -> None:
        if attribute in {ModuleConfig, BloomerpModule}:
            return

        try:
            if issubclass(attribute, ModuleConfig):
                self.register(attribute())
                return

            if issubclass(attribute, BloomerpModule):
                self.register(attribute.to_config())
                return
        except TypeError:
            return
        except Exception as exc:
            logger.error(
                "Error instantiating module '%s' in '%s': %s",
                attribute.__name__,
                source,
                exc,
            )

    def _add_model_to_module(self, module: ModuleConfig, model: type[Model]) -> None:
        module_key = module.full_id or module.id
        module_models = self._module_models.setdefault(module_key, {})
        module_models.setdefault(model._meta.label_lower, model)

    def _collect_descendant_ids(self, module_id: str) -> set[str]:
        descendants: set[str] = set()
        pending = [module_id]
        while pending:
            current_id = pending.pop()
            for child in self.get_children(current_id):
                child_id = child.full_id or child.id
                if child_id in descendants:
                    continue
                descendants.add(child_id)
                pending.append(child_id)
        return descendants

    def _rebuild_hierarchy_metadata(self) -> None:
        for module in self.items.values():
            module.full_id = module.full_id or (
                f"{module.parent_module_id}.{module.id}" if module.parent_module_id else module.id
            )

        for module in self.items.values():
            lineage = self.get_lineage(module.full_id or module.id)
            if not lineage:
                module.route_path = module.id.lower()
                module.root_module_id = module.full_id or module.id
                module.depth = 0
                continue

            module.route_path = "/".join(item.id.lower() for item in lineage)
            module.root_module_id = lineage[0].full_id or lineage[0].id
            module.depth = len(lineage) - 1

        rebuilt_items: dict[str, ModuleConfig] = {}
        for module in self.items.values():
            module_key = module.full_id or module.id
            rebuilt_items[module_key] = module
        self.items = rebuilt_items


module_registry = ModuleRegistry()
