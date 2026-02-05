from pyexpat import model
from django.db.models import Model
import yaml
from django.db import models
from typing import Optional, Dict, Any, Callable
from bloomerp.modules.definition import ModelConfig, ModuleConfig, SubModuleConfig
from bloomerp.modules.definition import (
    FieldConfig
)
from bloomerp.field_types import FieldType, FieldTypeDefinition


def _get_field_type_definition(field_type: str) -> FieldTypeDefinition:
    """Get field type definition for a field type."""
    field_definition = FieldType.from_id(field_type).value
    if not field_definition.allow_in_model:
        raise ValueError(f"Field type '{field_type}' is not allowed for model creation.")
    if field_definition.model_field_cls is None:
        raise ValueError(f"Field type '{field_type}' has no Django field class mapping.")
    return field_definition


def _get_validator_functions(field_config:FieldConfig) -> list[Callable]:
    # Get and import validators
    validator_functions = []
    if field_config.validators:
        for validator_path in field_config.validators:
            try:
                # Import validator function from module path
                module_path, function_name = validator_path.rsplit('.', 1)
                validator_module = __import__(module_path, fromlist=[function_name])
                validator_function = getattr(validator_module, function_name)
                validator_functions.append(validator_function)
            except (ImportError, AttributeError) as e:
                print(f"Warning: Could not import validator '{validator_path}': {e}")
                continue
    
    return validator_functions


def _get_callable(path: str) -> Callable:
    """Returns a callable for a particular path
    
    Example:
        path: django.db.models.CASCADE
    Returns:
        django.db.models.CASCADE
    
    Args:
        path: Dot-separated module path to the callable
        
    Returns:
        The callable object
        
    Raises:
        ImportError: If the module cannot be imported
        AttributeError: If the callable doesn't exist in the module
    """
    try:
        # Split the path into module and callable name
        module_path, callable_name = path.rsplit('.', 1)
        
        # Import the module
        module = __import__(module_path, fromlist=[callable_name])
        
        # Get the callable from the module
        callable_obj = getattr(module, callable_name)
        
        return callable_obj
    except (ImportError, AttributeError, ValueError) as e:
        raise ImportError(f"Could not import callable '{path}': {e}")


def _convert_string_to_callable(field_opts: dict) -> dict:
    """Convert string values to callables where needed.
    
    This function looks for field options that should be callables and converts
    string paths to actual callable objects.
    
    Common callable options:
    - on_delete: For foreign key relationships
    - default: When it's a callable default value (contains dots indicating module path)
    - call(...): When a string starts with "call(" and ends with ")", execute the callable
    - validators: Already handled separately
    """
    updated_opts = {}
    
    for field, value in field_opts.items():
        if field == 'on_delete' and isinstance(value, str):
            if hasattr(models, value):
                updated_opts[field] = getattr(models, value)
                continue

        if isinstance(value, str):
            # Handle call(...) pattern - execute the callable
            if value.startswith("call(") and value.endswith(")"):
                callable_path = value[5:-1]  # Remove "call(" and ")"
                try:
                    callable_obj = _get_callable(callable_path)
                    updated_opts[field] = callable_obj
                except ImportError as e:
                    print(f"Warning: Could not call '{callable_path}': {e}")
                    updated_opts[field] = value  # Keep original string if call fails
                continue
        
        # For all other cases, keep the original value
        updated_opts[field] = value
    
    return updated_opts


def get_model_class_name(model_name: str) -> str:
    """Generate class name from model name."""
    return ''.join(word.capitalize() for word in model_name.replace('-', ' ').replace('_', ' ').split())


def create_model_from_config(model_config: ModelConfig, sub_module: SubModuleConfig, module_config: ModuleConfig, model_lookup: Dict[str, str] = None) -> type[Model]:
    """Create a Django model class from Pydantic configuration objects."""
    attrs = {}
    # Process each field configuration
    for field_config in model_config.fields:
        field_definition = _get_field_type_definition(field_config.type)
        field_class = field_definition.model_field_cls
        default_opts = dict(field_definition.default_model_field_args)
        
        # Get validator functions
        validator_functions = _get_validator_functions(field_config)
        
        # Start with defaults, then override with field-specific options
        field_opts = {
            'help_text': field_config.description,
            'verbose_name': field_config.name,
            **default_opts
        }
        
        # Add validators if any were successfully imported
        if validator_functions:
            field_opts['validators'] = validator_functions
        
        # Apply any custom options from the field config
        if field_config.options:
            for key, value in field_config.options.items():
                # Handle YAML null key (parsed as None)
                if key is None:
                    field_opts['null'] = value
                else:
                    field_opts[key] = value
        
        # Handle 'to' in options for relationships
        if 'to' in field_opts and isinstance(field_opts['to'], str):
            to_ref = field_opts['to']
            # Check if it matches our reference format
            if model_lookup and to_ref in model_lookup:
                field_opts['to'] = f"bloomerp_modules.{model_lookup[to_ref]}"
        
        # Convert string values to callables where needed
        field_opts = _convert_string_to_callable(field_opts)
        
        # Create the field instance
        attrs[field_config.id] = field_class(**field_opts)
    
    # Create Meta class with model metadata
    class Meta:
        verbose_name = model_config.name
        db_table = f"{module_config.id}_{sub_module.id}_{model_config.id}"
        
        # if model_config.description:
        #     db_table_comment = model_config.description
            
        if model_config.name_plural:
            verbose_name_plural = model_config.name_plural
            
        # Handle custom permissions if they exist
        if model_config.custom_permissions:
            permissions = [(perm.id, perm.name) for perm in model_config.custom_permissions] if isinstance(model_config.custom_permissions, list) else []
    
    attrs['Meta'] = Meta
    attrs['__module__'] = 'bloomerp_modules.models'
    
    # Create class name from model name (remove spaces and special chars)
    model_class_name = get_model_class_name(model_config.name)
    
    # Add __str__ method if string_representation is provided
    if model_config.string_representation:
        def __str__(self):
            try:
                return model_config.string_representation.format(**{field.id: getattr(self, field.id) for field in model_config.fields})
            except Exception as e:
                return f"<{model_class_name} (error in __str__: {e})>"
        attrs['__str__'] = __str__
        
    # Add has_avatar attribute if specified
    if hasattr(model_config, 'has_avatar'):
        if model_config.has_avatar is False:
            attrs['avatar'] = None
    
    # Field layout - model_config.field_layout should now be a FieldLayout object.
    if getattr(model_config, 'field_layout', None):
        # Allow older list-based configs as a fallback
        if isinstance(model_config.field_layout, list):
            try:
                from bloomerp.models.base_bloomerp_model import FieldLayout

                attrs["field_layout"] = FieldLayout(sections=model_config.field_layout)
            except Exception:
                attrs["field_layout"] = model_config.field_layout
        else:
            attrs["field_layout"] = model_config.field_layout
    
    # Create and return the model class. Import BloomerpModel lazily to avoid circular imports.
    from bloomerp.models.base_bloomerp_model import BloomerpModel
    return type(model_class_name, (BloomerpModel,), attrs)


def scan_modules_directory() -> list[ModuleConfig]:
    """Scan the modules directory and load all module configurations using Pydantic models."""
    from pathlib import Path
    
    modules_dir = Path(__file__).parent.parent / 'modules'
    modules = []
    
    if not modules_dir.exists():
        return modules
    
    for module_dir in modules_dir.iterdir():
        if not module_dir.is_dir():
            continue
            
        module_config_path = module_dir / 'config.yaml'
        if not module_config_path.exists():
            continue
            
        # Load module config
        with open(module_config_path, 'r') as f:
            module_data = yaml.safe_load(f)
        
        # Scan for submodules
        sub_modules = []
        for item in module_dir.iterdir():
            if not item.is_dir():
                continue
                
            submodule_config_path = item / 'config.yaml'
            if not submodule_config_path.exists():
                continue
                
            # Load submodule config
            with open(submodule_config_path, 'r') as f:
                submodule_data = yaml.safe_load(f)
            
            # Scan for model files in the submodule directory
            models = []
            for model_file in item.iterdir():
                if model_file.is_file() and model_file.suffix == '.yaml' and model_file.name != 'config.yaml':
                    with open(model_file, 'r') as f:
                        model_data = yaml.safe_load(f)
                    
                    # Ensure model_data is not None and has required fields
                    if not model_data:
                        continue
                        
                    # Validate and clean model data before creating Pydantic model
                    clean_model_data = {
                        'id': model_data.get('id', model_file.stem),
                        'name': model_data.get('name', model_file.stem.replace('_', ' ').title()),
                        'description': model_data.get('description', ''),
                        'enabled': model_data.get('enabled', True),
                        'fields': model_data.get('fields', []),
                        'name_plural': model_data.get('name_plural'),
                        'custom_permissions': model_data.get('custom_permissions'),
                        'string_representation': model_data.get('string_representation'),
                        'has_avatar': model_data.get('has_avatar', True),
                        'field_layout':model_data.get('field_layout')
                        
                    }
                    
                    # Create ModelConfig from cleaned YAML data using Pydantic
                    try:
                        model_config = ModelConfig(**clean_model_data)
                        models.append(model_config)
                    except Exception as e:
                        print(f"Error loading model from {model_file}: {e}")
                        continue
            
            # Create SubModuleConfig from YAML data and add models
            clean_submodule_data = {
                'id': submodule_data.get('id', item.name),
                'name': submodule_data.get('name', item.name.replace('_', ' ').title()),
                'code': submodule_data.get('code', item.name.upper()),
                'description': submodule_data.get('description', ''),
                'enabled': submodule_data.get('enabled', True),
                'models': models
            }
            sub_module_config = SubModuleConfig(**clean_submodule_data)
            sub_modules.append(sub_module_config)
        
        # Create ModuleConfig from YAML data and add submodules
        clean_module_data = {
            'id': module_data.get('id', module_dir.name),
            'name': module_data.get('name', module_dir.name.replace('_', ' ').title()),
            'code': module_data.get('code', module_dir.name.upper()),
            'description': module_data.get('description', ''),
            'enabled': module_data.get('enabled', True),
            'icon': module_data.get('icon', '📁'),
            'sub_modules': sub_modules
        }
        module_config = ModuleConfig(**clean_module_data)
        modules.append(module_config)
    
    return modules


def load_all_models_from_modules() -> dict[str, type[Model]]:
    """Load all models from the modules directory structure."""
    modules = scan_modules_directory()
    models = {}
    
    # Build lookup map for model references
    model_lookup = {}
    for module in modules:
        for sub_module in module.sub_modules:
            for model_config in sub_module.models:
                ref = f"{module.id}.{sub_module.id}.{model_config.id}"
                class_name = get_model_class_name(model_config.name)
                model_lookup[ref] = class_name
    
    for module in modules:
        for sub_module in module.sub_modules:
            for model_config in sub_module.models:
                try:
                    model_class = create_model_from_config(
                        model_config, 
                        sub_module, 
                        module,
                        model_lookup
                    )
                    # Use a unique key to avoid conflicts
                    model_key = f"{module.id}_{sub_module.id}_{model_config.id}"
                    models[model_key] = model_class
                except Exception as e:
                    print(f"Error creating model '{model_config.name}' from module '{module.id}': {e}")
                    continue
    return models


def parse_yaml_config(yaml_file_path: str) -> ModuleConfig:
    """Parse YAML configuration file and return ModuleConfig object."""
    with open(yaml_file_path, 'r') as file:
        data = yaml.safe_load(file)
    
    module_data = data['module']
    
    # Parse sub-modules
    sub_modules = []
    if 'sub_modules' in module_data:
        for sub_module_data in module_data['sub_modules']:
            # Parse models
            models = []
            if 'models' in sub_module_data:
                for model_data in sub_module_data['models']:
                    # Parse fields
                    fields = []
                    if 'fields' in model_data:
                        for field_data in model_data['fields']:
                            field_config = FieldConfig(
                                id=field_data['id'],
                                name=field_data['name'],
                                type=field_data['type'],
                                description=field_data.get('description'),
                                options=field_data.get('options', {})
                            )
                            fields.append(field_config)
                    
                    model_config = ModelConfig(
                        id=model_data['id'],
                        name=model_data['name'],
                        description=model_data.get('description'),
                        fields=fields,
                        name_plural=model_data.get('name_plural'),
                        custom_permissions=model_data.get('custom_permissions')
                    )
                    models.append(model_config)
            
            sub_module_config = SubModuleConfig(
                id=sub_module_data['id'],
                name=sub_module_data['name'],
                code=sub_module_data['code'],
                models=models,
                description=sub_module_data.get('description')
            )
            sub_modules.append(sub_module_config)
    
    return ModuleConfig(
        id=module_data['id'],
        name=module_data['name'],
        code=module_data['code'],
        description=module_data.get('description'),
        icon=module_data['icon'],
        sub_modules=sub_modules
    )



