from django.core.management.base import BaseCommand
import os
import yaml
from pathlib import Path
from bloomerp.modules.definition import ModelConfig, ModuleConfig, SubModuleConfig
from bloomerp.modules.definition import FieldConfig
from bloomerp_modules.utils.dynamic_config_builder import DynamicConfigBuilder


class Command(BaseCommand):
    help = 'Create ERP items at different levels: module, submodule, model, or field'

    def __init__(self):
        super().__init__()
        self.config_builder = DynamicConfigBuilder(self.stdout, self.style)

    def add_arguments(self, parser):
        parser.add_argument(
            '--level', 
            type=str, 
            choices=['module', 'submodule', 'model', 'field'],
            help='Level of ERP item to create: module, submodule, model, or field'
        )
        parser.add_argument('--parent-module', type=str, help='Parent module ID (required for submodule, model, field)')
        parser.add_argument('--parent-submodule', type=str, help='Parent submodule ID (required for model, field)')
        parser.add_argument('--parent-model', type=str, help='Parent model ID (required for field)')
        parser.add_argument('--interactive', action='store_true', help='Run in interactive mode')

    def handle(self, *args, **options):
        level = options.get('level')
        
        if options['interactive'] or not level:
            self.stdout.write(self.style.SUCCESS('Creating ERP item interactively...'))
            level = self.get_level_interactive()
        
        # Route to appropriate handler based on level
        if level == 'module':
            self.handle_module_creation(options)
        elif level == 'submodule':
            self.handle_submodule_creation(options)
        elif level == 'model':
            self.handle_model_creation(options)
        elif level == 'field':
            self.handle_field_creation(options)
        else:
            self.stdout.write(self.style.ERROR('Invalid level. Choose from: module, submodule, model, field'))

    def get_level_interactive(self):
        """Get the level interactively"""
        self.stdout.write('\nChoose the level of ERP item to create:')
        self.stdout.write('1. Module')
        self.stdout.write('2. Submodule')
        self.stdout.write('3. Model')
        self.stdout.write('4. Field')
        
        while True:
            choice = input('\nEnter your choice (1-4): ').strip()
            if choice == '1':
                return 'module'
            elif choice == '2':
                return 'submodule'
            elif choice == '3':
                return 'model'
            elif choice == '4':
                return 'field'
            else:
                self.stdout.write(self.style.ERROR('Invalid choice. Please enter 1, 2, 3, or 4.'))

    def handle_module_creation(self, options):
        """Handle module creation"""
        self.stdout.write(self.style.SUCCESS('\nCreating a new module...'))
        
        # Get module data interactively
        module_data = self.config_builder.get_model_data_interactive(ModuleConfig, "module")
        
        # Validate and create
        if self.validate_module_data(module_data):
            self.create_module_structure(module_data)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created module "{module_data["name"]}" with ID "{module_data["id"]}"')
            )

    def handle_submodule_creation(self, options):
        """Handle submodule creation"""
        self.stdout.write(self.style.SUCCESS('\nCreating a new submodule...'))
        
        # Get parent module
        parent_module = options.get('parent_module')
        if not parent_module:
            parent_module = self.get_parent_module_interactive()
        
        # Get submodule data interactively (skip nested models for individual creation)
        submodule_data = self.config_builder.get_model_data_interactive(SubModuleConfig, "submodule", skip_fields=['models'])
        submodule_data['module'] = parent_module
        
        # Validate and create
        if self.validate_submodule_data(submodule_data):
            self.create_submodule_structure(submodule_data)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created submodule "{submodule_data["name"]}" with ID "{submodule_data["id"]}" in module "{parent_module}"')
            )

    def handle_model_creation(self, options):
        """Handle model creation"""
        self.stdout.write(self.style.SUCCESS('\nCreating a new model...'))
        
        # Get parent module and submodule
        parent_module = options.get('parent_module')
        parent_submodule = options.get('parent_submodule')
        
        if not parent_module or not parent_submodule:
            parent_module, parent_submodule = self.get_parent_module_submodule_interactive()
        
        # Get model data interactively (skip nested fields for individual creation)
        model_data = self.config_builder.get_model_data_interactive(ModelConfig, "model", skip_fields=['fields', 'custom_permissions'])
        model_data['module'] = parent_module
        model_data['submodule'] = parent_submodule
        
        # Validate and create
        if self.validate_model_data(model_data):
            self.create_model_structure(model_data)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created model "{model_data["name"]}" with ID "{model_data["id"]}" in {parent_module}/{parent_submodule}')
            )

    def handle_field_creation(self, options):
        """Handle field creation"""
        self.stdout.write(self.style.SUCCESS('\nAdding a new field to an existing model...'))
        
        # Get parent hierarchy
        parent_module = options.get('parent_module')
        parent_submodule = options.get('parent_submodule')
        parent_model = options.get('parent_model')
        
        if not all([parent_module, parent_submodule, parent_model]):
            parent_module, parent_submodule, parent_model = self.get_parent_hierarchy_interactive()
        
        # Get field data interactively
        field_data = self.config_builder.get_model_data_interactive(FieldConfig, "field", skip_fields=['options'])
        
        # Add field to model
        if self.add_field_to_model(parent_module, parent_submodule, parent_model, field_data):
            self.stdout.write(
                self.style.SUCCESS(f'Successfully added field "{field_data["name"]}" to model {parent_module}/{parent_submodule}/{parent_model}')
            )

    def get_parent_module_interactive(self):
        """Get parent module interactively"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        available_modules = []
        
        if modules_dir.exists():
            available_modules = [item.name for item in modules_dir.iterdir() if item.is_dir()]
        
        if available_modules:
            self.stdout.write('\nAvailable modules:')
            for module in available_modules:
                self.stdout.write(f'  - {module}')
            self.stdout.write('')
        
        while True:
            module_id = input('Enter parent module ID: ').strip()
            if not module_id:
                self.stdout.write(self.style.ERROR('Module ID is required'))
                continue
            
            if module_id in available_modules:
                return module_id
            else:
                self.stdout.write(self.style.WARNING(f'Module "{module_id}" not found. Available: {", ".join(available_modules)}'))

    def get_parent_module_submodule_interactive(self):
        """Get parent module and submodule interactively"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        available_items = []
        
        if modules_dir.exists():
            for item in modules_dir.iterdir():
                if item.is_dir():
                    # Look for submodules directly in the module directory
                    submodules = []
                    for sub in item.iterdir():
                        if sub.is_dir() and (sub / 'config.yaml').exists():
                            submodules.append(sub.name)
                    if submodules:
                        available_items.append((item.name, submodules))
        
        if available_items:
            self.stdout.write('\nAvailable modules and submodules:')
            for module_name, submodules in available_items:
                self.stdout.write(f'  Module: {module_name}')
                for submodule in submodules:
                    self.stdout.write(f'    - {submodule}')
            self.stdout.write('')
        
        module_id = input('Enter parent module ID: ').strip()
        submodule_id = input('Enter parent submodule ID: ').strip()
        
        return module_id, submodule_id

    def get_parent_hierarchy_interactive(self):
        """Get full parent hierarchy (module/submodule/model) interactively"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        available_items = []
        
        if modules_dir.exists():
            for module_item in modules_dir.iterdir():
                if module_item.is_dir():
                    for submodule_item in module_item.iterdir():
                        if submodule_item.is_dir() and (submodule_item / 'config.yaml').exists():
                            # Look for model files in submodule
                            models = []
                            for model_file in submodule_item.iterdir():
                                if model_file.is_file() and model_file.suffix == '.yaml' and model_file.name != 'config.yaml':
                                    models.append(model_file.stem)
                            if models:
                                available_items.append((module_item.name, submodule_item.name, models))
        
        if available_items:
            self.stdout.write('\nAvailable modules/submodules/models:')
            for module_name, submodule_name, models in available_items:
                self.stdout.write(f'  {module_name}/{submodule_name}:')
                for model in models:
                    self.stdout.write(f'    - {model}')
            self.stdout.write('')
        
        module_id = input('Enter parent module ID: ').strip()
        submodule_id = input('Enter parent submodule ID: ').strip()
        model_id = input('Enter parent model ID: ').strip()
        
        return module_id, submodule_id, model_id

    def validate_module_data(self, module_data):
        """Validate module data before creation"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        
        # Check if module already exists
        module_dir = modules_dir / module_data['id']
        if module_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Module "{module_data["id"]}" already exists at {module_dir}')
            )
            return False

        return True

    def validate_submodule_data(self, submodule_data):
        """Validate submodule data before creation"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        
        # Check if parent module exists
        module_dir = modules_dir / submodule_data['module']
        if not module_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Parent module "{submodule_data["module"]}" does not exist at {module_dir}')
            )
            return False
        
        # Check if submodule already exists
        submodule_dir = module_dir / submodule_data['id']
        if submodule_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Submodule "{submodule_data["id"]}" already exists at {submodule_dir}')
            )
            return False

        return True

    def validate_model_data(self, model_data):
        """Validate model data before creation"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        
        # Check if parent module exists
        module_dir = modules_dir / model_data['module']
        if not module_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Parent module "{model_data["module"]}" does not exist at {module_dir}')
            )
            return False
        
        # Check if parent submodule exists
        submodule_dir = module_dir / model_data['submodule']
        if not submodule_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Parent submodule "{model_data["submodule"]}" does not exist at {submodule_dir}')
            )
            return False
        
        # Check if model already exists
        model_file_path = submodule_dir / f"{model_data['id']}.yaml"
        if model_file_path.exists():
            self.stdout.write(
                self.style.ERROR(f'Model "{model_data["id"]}" already exists at {model_file_path}')
            )
            return False

        return True

    def create_module_structure(self, module_data):
        """Create the module directory structure and files"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        
        # Create module directory structure
        module_dir = modules_dir / module_data['id']
        module_dir.mkdir(exist_ok=True)
        
        # Create module config.yaml
        module_config_path = module_dir / 'config.yaml'
        module_config_simple = {
            'id': module_data['id'],
            'code': module_data['code'],
            'name': module_data['name'],
            'description': module_data.get('description', ''),
            'icon': module_data['icon']
        }
        
        with open(module_config_path, 'w') as f:
            yaml.dump(module_config_simple, f, default_flow_style=False, sort_keys=False)
        
        self.stdout.write(f'Created module config: {module_config_path}')

        # Create any submodules that were defined interactively
        if 'sub_modules' in module_data and module_data['sub_modules']:
            for submodule_data in module_data['sub_modules']:
                self.create_submodule_from_data(module_dir, submodule_data, module_data['id'])

    def create_submodule_structure(self, submodule_data):
        """Create the submodule directory structure and files"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        module_dir = modules_dir / submodule_data['module']
        
        # Create submodule directory directly in module directory
        submodule_dir = module_dir / submodule_data['id']
        submodule_dir.mkdir(exist_ok=True)
        
        # Create submodule config.yaml
        submodule_config_path = submodule_dir / 'config.yaml'
        submodule_config = {
            'id': submodule_data['id'],
            'name': submodule_data['name'],
            'code': submodule_data['code'],
            'description': submodule_data.get('description', '')
        }
        
        with open(submodule_config_path, 'w') as f:
            yaml.dump(submodule_config, f, default_flow_style=False, sort_keys=False)
        
        self.stdout.write(f'Created submodule config: {submodule_config_path}')

        # Create any models that were defined interactively (directly in submodule directory)
        if 'models' in submodule_data and submodule_data['models']:
            for model_data in submodule_data['models']:
                self.create_model_from_data(submodule_dir, model_data)

    def create_model_structure(self, model_data):
        """Create the model file"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        submodule_dir = modules_dir / model_data['module'] / model_data['submodule']
        
        # Create model YAML file directly in submodule directory
        model_file_path = submodule_dir / f"{model_data['id']}.yaml"
        
        model_config = {
            'name': model_data['name'],
            'id': model_data['id'],
            'description': model_data.get('description', ''),
            'fields': model_data.get('fields', [])
        }
        
        # Add optional fields if they exist
        if model_data.get('name_plural'):
            model_config['name_plural'] = model_data['name_plural']
        if model_data.get('custom_permissions'):
            model_config['custom_permissions'] = model_data['custom_permissions']
        
        with open(model_file_path, 'w') as f:
            yaml.dump(model_config, f, default_flow_style=False, sort_keys=False)
        
        self.stdout.write(f'Created model file: {model_file_path}')

    def add_field_to_model(self, module_id, submodule_id, model_id, field_data):
        """Add a field to an existing model"""
        modules_dir = Path(__file__).parent.parent.parent / 'modules'
        model_file_path = modules_dir / module_id / submodule_id / f"{model_id}.yaml"
        
        if not model_file_path.exists():
            self.stdout.write(
                self.style.ERROR(f'Model file does not exist: {model_file_path}')
            )
            return False
        
        # Read existing model
        with open(model_file_path, 'r') as f:
            model_config = yaml.safe_load(f)
        
        # Initialize fields if not exists
        if 'fields' not in model_config:
            model_config['fields'] = []
        
        # Check if field already exists
        existing_field_ids = [field.get('id') for field in model_config['fields']]
        if field_data['id'] in existing_field_ids:
            self.stdout.write(
                self.style.ERROR(f'Field "{field_data["id"]}" already exists in model "{model_id}"')
            )
            return False
        
        # Add new field
        model_config['fields'].append(field_data)
        
        # Write back to file
        with open(model_file_path, 'w') as f:
            yaml.dump(model_config, f, default_flow_style=False, sort_keys=False)
        
        self.stdout.write(f'Updated model file: {model_file_path}')
        return True

    def create_submodule_from_data(self, module_dir, submodule_data, module_id):
        """Create a submodule from the interactive data"""
        # Create submodule directory
        submodule_dir = module_dir / submodule_data['id']
        submodule_dir.mkdir(exist_ok=True)
        
        # Create submodule config
        submodule_config_path = submodule_dir / 'config.yaml'
        submodule_config = {
            'id': submodule_data['id'],
            'name': submodule_data['name'],
            'code': submodule_data['code'],
            'description': submodule_data.get('description', '')
        }
        
        with open(submodule_config_path, 'w') as f:
            yaml.dump(submodule_config, f, default_flow_style=False, sort_keys=False)
        
        # Create any models that were defined interactively (directly in submodule directory)
        if 'models' in submodule_data and submodule_data['models']:
            for model_data in submodule_data['models']:
                self.create_model_from_data(submodule_dir, model_data)
        
        self.stdout.write(f'Created submodule: {submodule_dir}')

    def create_model_from_data(self, submodule_dir, model_data):
        """Create a model file from the interactive data"""
        model_file_path = submodule_dir / f"{model_data['id']}.yaml"
        
        model_config = {
            'name': model_data['name'],
            'id': model_data['id'],
            'description': model_data.get('description', ''),
            'fields': model_data.get('fields', [])
        }
        
        # Add optional fields if they exist
        if model_data.get('name_plural'):
            model_config['name_plural'] = model_data['name_plural']
        if model_data.get('custom_permissions'):
            model_config['custom_permissions'] = model_data['custom_permissions']
        
        with open(model_file_path, 'w') as f:
            yaml.dump(model_config, f, default_flow_style=False, sort_keys=False)
        
        self.stdout.write(f'Created model file: {model_file_path}')
