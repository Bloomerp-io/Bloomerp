from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from bloomerp.modules.definition import FieldConfig, ModelConfig, ModuleConfig
from bloomerp_modules.utils.dynamic_config_builder import DynamicConfigBuilder


class Command(BaseCommand):
    help = "Create ERP items at different levels: module, model, or field"

    def __init__(self):
        super().__init__()
        self.config_builder = DynamicConfigBuilder(self.stdout, self.style)

    def add_arguments(self, parser):
        parser.add_argument("--level", type=str, choices=["module", "model", "field"])
        parser.add_argument("--parent-module", type=str, help="Parent module ID for nested modules, models, and fields")
        parser.add_argument("--parent-model", type=str, help="Parent model ID when adding a field")
        parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")

    def handle(self, *args, **options):
        level = options.get("level")
        if options["interactive"] or not level:
            level = self._get_level_interactive()

        if level == "module":
            self._handle_module_creation(options)
            return
        if level == "model":
            self._handle_model_creation(options)
            return
        if level == "field":
            self._handle_field_creation(options)
            return

        self.stdout.write(self.style.ERROR("Invalid level. Choose from: module, model, field"))

    def _get_level_interactive(self) -> str:
        self.stdout.write("\nChoose the level of ERP item to create:")
        self.stdout.write("1. Module")
        self.stdout.write("2. Model")
        self.stdout.write("3. Field")
        while True:
            choice = input("\nEnter your choice (1-3): ").strip()
            if choice == "1":
                return "module"
            if choice == "2":
                return "model"
            if choice == "3":
                return "field"
            self.stdout.write(self.style.ERROR("Invalid choice. Please enter 1, 2, or 3."))

    def _modules_dir(self) -> Path:
        return Path(__file__).parent.parent.parent / "modules"

    def _find_module_dir(self, module_id: str) -> Path | None:
        for config_path in self._modules_dir().glob("**/config.yaml"):
            with config_path.open("r") as file:
                data = yaml.safe_load(file) or {}
            if data.get("id", config_path.parent.name) == module_id:
                return config_path.parent
        return None

    def _get_parent_module_id(self, prompt: str = "Enter parent module ID (leave empty for root): ") -> str | None:
        module_id = input(prompt).strip()
        return module_id or None

    def _handle_module_creation(self, options):
        self.stdout.write(self.style.SUCCESS("\nCreating a new module..."))
        module_data = self.config_builder.get_model_data_interactive(
            ModuleConfig,
            "module",
            skip_fields=["route_path", "root_module_id", "depth"],
        )
        parent_module_id = options.get("parent_module")
        if parent_module_id is None and options.get("interactive"):
            parent_module_id = self._get_parent_module_id()
        if parent_module_id:
            module_data["parent_module_id"] = parent_module_id
        self._create_module_structure(module_data)
        self.stdout.write(self.style.SUCCESS(f'Successfully created module "{module_data["name"]}"'))

    def _handle_model_creation(self, options):
        self.stdout.write(self.style.SUCCESS("\nCreating a new model..."))
        parent_module = options.get("parent_module") or self._get_parent_module_id("Enter parent module ID: ")
        if not parent_module:
            self.stdout.write(self.style.ERROR("A parent module is required for model creation."))
            return
        model_data = self.config_builder.get_model_data_interactive(ModelConfig, "model", skip_fields=["fields", "custom_permissions"])
        self._create_model_structure(parent_module, model_data)
        self.stdout.write(self.style.SUCCESS(f'Successfully created model "{model_data["name"]}" in module "{parent_module}"'))

    def _handle_field_creation(self, options):
        self.stdout.write(self.style.SUCCESS("\nAdding a new field to an existing model..."))
        parent_module = options.get("parent_module") or self._get_parent_module_id("Enter parent module ID: ")
        parent_model = options.get("parent_model") or input("Enter parent model ID: ").strip()
        if not parent_module or not parent_model:
            self.stdout.write(self.style.ERROR("Parent module and model are required for field creation."))
            return
        field_data = self.config_builder.get_model_data_interactive(FieldConfig, "field", skip_fields=["options"])
        if self._add_field_to_model(parent_module, parent_model, field_data):
            self.stdout.write(self.style.SUCCESS(f'Successfully added field "{field_data["name"]}" to model "{parent_model}"'))

    def _create_module_structure(self, module_data: dict) -> None:
        modules_dir = self._modules_dir()
        parent_module_id = module_data.get("parent_module_id")
        parent_dir = self._find_module_dir(parent_module_id) if parent_module_id else modules_dir
        if parent_dir is None:
            raise ValueError(f'Parent module "{parent_module_id}" could not be found.')

        module_dir = parent_dir / module_data["id"]
        module_dir.mkdir(parents=True, exist_ok=True)

        config_path = module_dir / "config.yaml"
        payload = {
            "id": module_data["id"],
            "name": module_data["name"],
            "code": module_data["code"],
            "description": module_data.get("description", ""),
            "icon": module_data.get("icon", "fa-solid fa-folder"),
            "enabled": module_data.get("enabled", True),
            "visible": module_data.get("visible", True),
        }
        if parent_module_id:
            payload["parent_module_id"] = parent_module_id

        with config_path.open("w") as file:
            yaml.dump(payload, file, default_flow_style=False, sort_keys=False)

    def _create_model_structure(self, module_id: str, model_data: dict) -> None:
        module_dir = self._find_module_dir(module_id)
        if module_dir is None:
            raise ValueError(f'Parent module "{module_id}" could not be found.')

        model_file_path = module_dir / f"{model_data['id']}.yaml"
        payload = {
            "id": model_data["id"],
            "name": model_data["name"],
            "description": model_data.get("description", ""),
            "enabled": model_data.get("enabled", True),
            "fields": model_data.get("fields", []),
        }
        if model_data.get("name_plural"):
            payload["name_plural"] = model_data["name_plural"]

        with model_file_path.open("w") as file:
            yaml.dump(payload, file, default_flow_style=False, sort_keys=False)

    def _add_field_to_model(self, module_id: str, model_id: str, field_data: dict) -> bool:
        module_dir = self._find_module_dir(module_id)
        if module_dir is None:
            self.stdout.write(self.style.ERROR(f'Parent module "{module_id}" could not be found.'))
            return False

        model_file_path = module_dir / f"{model_id}.yaml"
        if not model_file_path.exists():
            self.stdout.write(self.style.ERROR(f'Model "{model_id}" could not be found in module "{module_id}".'))
            return False

        with model_file_path.open("r") as file:
            model_config = yaml.safe_load(file) or {}

        fields = model_config.setdefault("fields", [])
        fields.append(
            {
                "id": field_data["id"],
                "name": field_data["name"],
                "type": field_data["type"],
                "description": field_data.get("description", ""),
                "validators": field_data.get("validators", []),
            }
        )

        with model_file_path.open("w") as file:
            yaml.dump(model_config, file, default_flow_style=False, sort_keys=False)

        return True
