from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Tuple
from bloomerp.models.base_bloomerp_model import FieldLayout
from django.db.models import Model
import logging
import importlib
import inspect
import pkgutil
from django import apps

logger = logging.getLogger(__name__)

class BaseConfig(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    enabled: bool = True


class FieldConfig(BaseConfig):
    type: str
    options: Optional[dict] = None
    validators : list[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    id:str
    name:str


class ModelConfig(BaseConfig):
    name_plural: Optional[str] = None
    fields: list[FieldConfig] = Field(default_factory=list)
    custom_permissions: Optional[PermissionConfig] = Field(default_factory=list)
    string_representation: Optional[str] = None
    field_layout: Optional[FieldLayout] = Field(default_factory=FieldLayout)


class SubModuleConfig(BaseConfig):
    code: str
    module_id: str
    icon: Optional[str] = None
    models: list[ModelConfig] = Field(default_factory=list)


class ModuleConfig(BaseConfig):
    code: str
    icon: str = "fa-solid fa-folder"
    sub_modules: list[SubModuleConfig] = Field(default_factory=list)
    visible: bool = True

# ----------------------
# Module Registry
# ----------------------

class ModuleRegistry:
    """
    A registry for managing module configurations in the Bloomerp system.
    Provides functionality to register, retrieve, and manage modules.
    """

    def __init__(self):
        self.items: Dict[str, ModuleConfig] = {}
        self._module_models: Dict[str, Dict[str, type[Model]]] = {}
        self._submodule_models: Dict[Tuple[str, str], Dict[str, type[Model]]] = {}
        self._submodule_module_map: Dict[str, str] = {}

    def register(self, module: ModuleConfig) -> None:
        """
        Register a module in the registry.

        Args:
            module: The ModuleConfig instance to register

        Raises:
            ValueError: If module with same ID already exists
        """
        if module.id in self.items:
            logger.warning(f"Module with ID '{module.id}' already exists. Overwriting.")

        for sub_module in module.sub_modules:
            if not sub_module.module_id or sub_module.module_id != module.id:
                if sub_module.module_id and sub_module.module_id != module.id:
                    logger.warning(
                        "Submodule '%s' declared under module '%s' but has module_id '%s'. "
                        "Overriding to '%s'.",
                        sub_module.id,
                        module.id,
                        sub_module.module_id,
                        module.id,
                    )
                sub_module.module_id = module.id

            existing_module_id = self._submodule_module_map.get(sub_module.id)
            if existing_module_id and existing_module_id != module.id:
                logger.warning(
                    "Submodule '%s' already belongs to module '%s'; skipping registration under '%s'.",
                    sub_module.id,
                    existing_module_id,
                    module.id,
                )
                continue
            self._submodule_module_map[sub_module.id] = module.id

        self.items[module.id] = module
        logger.info(f"Registered module: {module.name} (ID: {module.id})")

    def get(self, module_id: str) -> Optional[ModuleConfig]:
        """
        Retrieve a module by its ID.

        Args:
            module_id: The ID of the module to retrieve

        Returns:
            The ModuleConfig instance if found, None otherwise
        """
        return self.items.get(module_id)

    def get_all(self) -> Dict[str, ModuleConfig]:
        """
        Get all registered modules.

        Returns:
            Dictionary of all registered modules
        """
        return self.items.copy()

    def get_enabled(self) -> Dict[str, ModuleConfig]:
        """
        Get all enabled modules.

        Returns:
            Dictionary of enabled modules only
        """
        return {
            module_id: module
            for module_id, module in self.items.items()
            if module.enabled
        }

    def unregister(self, module_id: str) -> bool:
        """
        Unregister a module from the registry.

        Args:
            module_id: The ID of the module to unregister

        Returns:
            True if module was removed, False if module was not found
        """
        if module_id in self.items:
            removed_module = self.items.pop(module_id)
            logger.info(f"Unregistered module: {removed_module.name} (ID: {module_id})")
            return True
        return False

    def exists(self, module_id: str) -> bool:
        """
        Check if a module is registered.

        Args:
            module_id: The ID of the module to check

        Returns:
            True if module exists, False otherwise
        """
        return module_id in self.items

    def enable_module(self, module_id: str) -> bool:
        """
        Enable a registered module.

        Args:
            module_id: The ID of the module to enable

        Returns:
            True if module was enabled, False if module was not found
        """
        if module_id in self.items:
            self.items[module_id].enabled = True
            logger.info(f"Enabled module: {module_id}")
            return True
        return False

    def disable_module(self, module_id: str) -> bool:
        """
        Disable a registered module.

        Args:
            module_id: The ID of the module to disable

        Returns:
            True if module was disabled, False if module was not found
        """
        if module_id in self.items:
            self.items[module_id].enabled = False
            logger.info(f"Disabled module: {module_id}")
            return True
        return False

    def list_module_ids(self) -> List[str]:
        """
        Get a list of all registered module IDs.

        Returns:
            List of module IDs
        """
        return list(self.items.keys())

    def clear(self) -> None:
        """
        Clear all registered modules.
        """
        self.items.clear()
        self._module_models.clear()
        self._submodule_models.clear()
        self._submodule_module_map.clear()
        logger.info("Cleared all modules from registry")

    def __len__(self) -> int:
        """
        Get the number of registered modules.

        Returns:
            Number of registered modules
        """
        return len(self.items)

    def __contains__(self, module_id: str) -> bool:
        """
        Check if a module is registered using 'in' operator.

        Args:
            module_id: The ID of the module to check

        Returns:
            True if module exists, False otherwise
        """
        return module_id in self.items

    def __str__(self) -> str:
        """
        String representation of the registry.

        Returns:
            String describing the registry contents
        """
        enabled_count = len(self.get_enabled())
        return f"ModuleRegistry({len(self.items)} modules, {enabled_count} enabled)"
    
    def refresh(self) -> None:
        """Refreshes the module registry
        """
        # Clear items
        #self.clear()
        
        # First register all of the modules
        for app_config in apps.apps.get_app_configs():
            
            # Discover by going through the modules folder in every app
            # -> look through every file in that folder and search for 
            # classes that are strictly a subclass of ModuleConfig
            try:
                module = importlib.import_module(f"{app_config.name}.modules")
            except ModuleNotFoundError:
                continue

            # Register any ModuleConfig classes defined directly in the package
            for _, attribute in inspect.getmembers(module, inspect.isclass):
                if attribute is ModuleConfig:
                    continue
                if issubclass(attribute, ModuleConfig):
                    try:
                        module_instance = attribute()
                        self.register(module_instance)
                    except Exception as e:
                        logger.error(
                            f"Error instantiating module '{attribute.__name__}' in app '{app_config.name}': {e}"
                        )

            # Discover and register ModuleConfig classes in module files
            if not hasattr(module, "__path__"):
                continue

            for _, module_name, _ in pkgutil.iter_modules(module.__path__, module.__name__ + "."):
                if module_name.endswith(".definition"):
                    continue
                try:
                    submodule = importlib.import_module(module_name)
                except Exception as e:
                    logger.error(f"Error importing module '{module_name}': {e}")
                    continue
                for _, attribute in inspect.getmembers(submodule, inspect.isclass):
                    if attribute is ModuleConfig:
                        continue
                    if issubclass(attribute, ModuleConfig):
                        try:
                            module_instance = attribute()
                            self.register(module_instance)
                        except Exception as e:
                            logger.error(
                                f"Error instantiating module '{attribute.__name__}' in '{module_name}': {e}"
                            )

        # After registering module definitions, attach model mappings
        self._register_models_from_apps()

    def get_models_for_module(self, module_id: str) -> list[type[Model]]:
        """Return all model classes for a given module."""
        # self._register_models_from_apps()
        return list(self._module_models.get(module_id, {}).values())

    def get_models_for_submodule(self, module_id: str, submodule_id: str) -> list[type[Model]]:
        """Return all model classes for a given module + submodule."""
        # self._register_models_from_apps()
        return list(self._submodule_models.get((module_id, submodule_id), {}).values())

    def get_modules_for_model(self, model: type[Model]) -> list[ModuleConfig]:
        """Return the module config for a given model class."""
        model_key = model._meta.label_lower
        modules = []
        for module_id, models in self._module_models.items():
            if model_key in models:
                module = self.items.get(module_id)
                if module:
                    modules.append(module.copy(update={"name": module.id}))
        return modules
        
    
    def _register_models_from_apps(self) -> None:
        """Scan installed apps and map models to modules/submodules."""
        for model in apps.apps.get_models():
            bloomerp_meta = getattr(model, "Bloomerp", None)
            modules_spec = getattr(bloomerp_meta, "modules", None) if bloomerp_meta else None

            if not modules_spec:
                modules_spec = ["misc"]

            for module_entry in self._normalize_modules_spec(modules_spec):
                module_id = module_entry["module_id"]
                sub_modules = module_entry.get("sub_modules", [])

                module_config = self._get_or_create_module(module_id)
                self._add_model_to_module(module_config, model)

                for sub_module_entry in sub_modules:
                    sub_module_config = self._get_or_create_submodule(
                        module_config,
                        sub_module_entry,
                    )
                    if not sub_module_config:
                        continue
                    self._add_model_to_submodule(module_config, sub_module_config, model)

    def _normalize_modules_spec(self, modules_spec: Any) -> list[dict]:
        """Normalize model `modules` definitions into module + submodule entries."""
        entries: list[Any]

        if modules_spec is None:
            return []

        if isinstance(modules_spec, dict):
            entries = [modules_spec]
        elif isinstance(modules_spec, (list, tuple, set)):
            entries = list(modules_spec)
        else:
            entries = [modules_spec]

        normalized: list[dict] = []

        for entry in entries:
            if isinstance(entry, str):
                module_id, submodule_id = self._split_module_ref(entry)
                if not module_id:
                    continue
                if submodule_id:
                    normalized.append(
                        {
                            "module_id": module_id,
                            "sub_modules": [{"id": submodule_id}],
                        }
                    )
                else:
                    normalized.append({"module_id": module_id, "sub_modules": []})
                continue

            if isinstance(entry, dict):
                module_id = entry.get("module") or entry.get("module_id") or entry.get("id")
                sub_modules = entry.get("sub_modules") or entry.get("submodules") or entry.get("sub_module") or []

                if not module_id:
                    for sub_entry in self._ensure_list(sub_modules):
                        if isinstance(sub_entry, str) and "." in sub_entry:
                            mod_id, sub_id = self._split_module_ref(sub_entry)
                            if mod_id and sub_id:
                                normalized.append(
                                    {
                                        "module_id": mod_id,
                                        "sub_modules": [{"id": sub_id}],
                                    }
                                )
                    continue

                normalized.append(
                    {
                        "module_id": module_id,
                        "sub_modules": self._normalize_submodules(sub_modules),
                    }
                )
                continue

        return normalized

    def _normalize_submodules(self, sub_modules: Any) -> list[dict]:
        normalized: list[dict] = []
        for entry in self._ensure_list(sub_modules):
            if isinstance(entry, str):
                _, submodule_id = self._split_module_ref(entry)
                submodule_id = submodule_id or entry
                if submodule_id:
                    normalized.append({"id": submodule_id})
                continue

            if isinstance(entry, dict):
                sub_id = entry.get("id") or entry.get("sub_module") or entry.get("submodule") or entry.get("code")
                if not sub_id:
                    continue
                normalized.append(
                    {
                        "id": sub_id,
                        "name": entry.get("name"),
                        "code": entry.get("code") or sub_id,
                        "icon": entry.get("icon"),
                        "description": entry.get("description"),
                    }
                )
        return normalized

    def _split_module_ref(self, entry: str) -> tuple[str | None, str | None]:
        entry = entry.strip()
        if not entry:
            return None, None
        if "." in entry:
            module_id, submodule_id = entry.split(".", 1)
            return module_id.strip(), submodule_id.strip()
        return entry.strip(), None

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def _get_or_create_module(self, module_id: str) -> ModuleConfig:
        module = self.items.get(module_id)
        if module:
            return module

        module = ModuleConfig(
            id=module_id,
            name=module_id.replace("_", " ").replace("-", " ").title(),
            code=module_id,
            icon="fa-solid fa-folder",
            description=None,
            enabled=True,
            sub_modules=[],
        )
        self.register(module)
        return module

    def _get_or_create_submodule(
        self,
        module: ModuleConfig,
        sub_module_entry: dict,
    ) -> Optional[SubModuleConfig]:
        sub_id = sub_module_entry.get("id")
        if not sub_id:
            return None

        existing_module_id = self._submodule_module_map.get(sub_id)
        if existing_module_id and existing_module_id != module.id:
            logger.warning(
                "Submodule '%s' already belongs to module '%s'; skipping association with '%s'.",
                sub_id,
                existing_module_id,
                module.id,
            )
            return None

        for sub_module in module.sub_modules:
            if sub_module.id == sub_id:
                if sub_module.icon is None and sub_module_entry.get("icon"):
                    sub_module.icon = sub_module_entry.get("icon")
                return sub_module

        sub_module = SubModuleConfig(
            id=sub_id,
            name=(sub_module_entry.get("name") or sub_id.replace("_", " ").replace("-", " ").title()),
            code=(sub_module_entry.get("code") or sub_id),
            module_id=module.id,
            icon=sub_module_entry.get("icon"),
            description=sub_module_entry.get("description"),
            enabled=True,
            models=[],
        )
        module.sub_modules.append(sub_module)
        self._submodule_module_map[sub_id] = module.id
        return sub_module

    def _add_model_to_module(self, module: ModuleConfig, model: type[Model]) -> None:
        module_models = self._module_models.setdefault(module.id, {})
        model_key = model._meta.label_lower
        if model_key in module_models:
            return
        module_models[model_key] = model

    def _add_model_to_submodule(
        self, module: ModuleConfig, sub_module: SubModuleConfig, model: type[Model]
    ) -> None:
        sub_models = self._submodule_models.setdefault((module.id, sub_module.id), {})
        model_key = model._meta.label_lower
        if model_key in sub_models:
            return
        sub_models[model_key] = model
        if not any(existing.id == model._meta.model_name for existing in sub_module.models):
            sub_module.models.append(self._model_to_config(model))

    def _model_to_config(self, model: type[Model]) -> ModelConfig:
        return ModelConfig(
            id=model._meta.model_name,
            name=str(model._meta.verbose_name).title(),
            description=(model.__doc__ or None),
            enabled=True,
            fields=[],
            name_plural=str(model._meta.verbose_name_plural).title()
            if model._meta.verbose_name_plural
            else None,
        )

module_registry = ModuleRegistry()
