from typing import get_origin, get_args, Any, Dict, List
from pydantic import BaseModel
import inspect


class DynamicConfigBuilder:
    """Utility class for dynamically building Pydantic model instances with recursive list and dict handling."""
    
    def __init__(self, stdout_writer=None, style=None):
        self.stdout = stdout_writer
        self.style = style
    
    def log(self, message, style_name=None):
        """Helper to log messages if stdout is available."""
        if self.stdout:
            if style_name and self.style:
                self.stdout.write(getattr(self.style, style_name)(message))
            else:
                self.stdout.write(message)
    
    def get_model_data_interactive(self, model_class: type[BaseModel], instance_name: str = None, skip_fields: List[str] = None) -> Dict[str, Any]:
        """
        Recursively build a Pydantic model instance through interactive prompts.
        
        Args:
            model_class: The Pydantic model class to build
            instance_name: Human-readable name for this instance (e.g., "module", "submodule")
            skip_fields: List of field names to skip
        
        Returns:
            Dictionary with the model data
        """
        if not instance_name:
            instance_name = model_class.__name__.replace('Config', '').lower()
        
        skip_fields = skip_fields or []
        
        self.log(f'\n=== Creating {instance_name.title()} ===\n')
        
        data = {}
        
        # Process fields in a specific order to ensure required fields come first
        sorted_fields = self._sort_fields_by_importance(model_class.model_fields)
        
        for field_name, field_info in sorted_fields:
            if field_name in skip_fields:
                continue
                
            field_type = field_info.annotation
            is_required = field_info.default is ... and not field_info.default_factory
            default_value = field_info.default if field_info.default is not ... else None
            
            # Handle the field based on its type
            value = self._handle_field_input(field_name, field_type, is_required, default_value, instance_name)
            
            # Set the value if provided or if it's required
            if value is not None or is_required:
                data[field_name] = value
            elif default_value is not None:
                data[field_name] = default_value
        
        return data
    
    def _sort_fields_by_importance(self, fields):
        """Sort fields to ensure logical order: required fields first, then lists last."""
        field_items = list(fields.items())
        
        # Sort by: required fields first, then simple fields, then lists/complex types last
        def field_priority(field_item):
            field_name, field_info = field_item
            field_type = field_info.annotation
            is_required = field_info.default is ... and not field_info.default_factory
            
            # Priority order (lower number = higher priority)
            if field_name == 'id':
                return 0  # ID always first
            elif field_name == 'name':
                return 1  # Name second
            elif is_required:
                return 2  # Other required fields
            elif get_origin(field_type) == list:
                return 5  # Lists last
            elif get_origin(field_type) == dict:
                return 4  # Dicts second to last
            else:
                return 3  # Other optional fields
        
        return sorted(field_items, key=field_priority)
    
    def _handle_field_input(self, field_name: str, field_type: Any, is_required: bool, default_value: Any, context: str) -> Any:
        """Handle input for a specific field based on its type."""
        
        # Handle Optional types (Union[X, None])
        origin = get_origin(field_type)
        args = get_args(field_type)
        
        if origin is not None:
            if origin == list:
                return self._handle_list_field(field_name, args[0], context)
            elif origin == dict:
                return self._handle_dict_field(field_name, args, context)
            elif hasattr(field_type, '__origin__') and len(args) == 2 and type(None) in args:
                # This is Optional[T], get the non-None type
                actual_type = args[0] if args[1] is type(None) else args[1]
                return self._handle_simple_field(field_name, actual_type, is_required, default_value)
        
        # Handle Pydantic models (nested objects)
        if inspect.isclass(field_type) and issubclass(field_type, BaseModel):
            return self._handle_nested_model_field(field_name, field_type, is_required, context)
        
        # Handle simple types
        return self._handle_simple_field(field_name, field_type, is_required, default_value)
    
    def _handle_simple_field(self, field_name: str, field_type: Any, is_required: bool, default_value: Any) -> Any:
        """Handle simple field types like str, int, bool."""
        
        # Create prompt
        prompt = f'Enter {field_name.replace("_", " ")} '
        if not is_required and default_value is not None:
            prompt += f'(optional, default: {default_value}): '
        elif not is_required:
            prompt += '(optional): '
        else:
            prompt += '(required): '
        
        # Field-specific validation
        if field_name == 'id':
            prompt = f'Enter {field_name} (lowercase, no spaces, underscores allowed): '
            value = input(prompt).strip()
            while value and (not value.islower() or ' ' in value):
                self.log('ID must be lowercase with no spaces (underscores allowed)', 'ERROR')
                value = input(prompt).strip()
        elif field_name == 'code':
            prompt = f'Enter {field_name} (uppercase recommended): '
            value = input(prompt).strip()
        elif field_name == 'icon':
            prompt = 'Enter FontAwesome icon class (e.g., "fa-users"): '
            value = input(prompt).strip()
        elif field_type == bool:
            prompt = f'Enable {field_name.replace("_", " ")} (y/n, default: {"y" if default_value else "n"}): '
            value = input(prompt).strip().lower()
            if not value:
                return default_value
            return value in ['y', 'yes', 'true', '1']
        elif field_type == int:
            value = input(prompt).strip()
            if value:
                try:
                    return int(value)
                except ValueError:
                    self.log('Invalid integer value, using default', 'ERROR')
                    return default_value
        else:
            value = input(prompt).strip()
        
        # Validate required fields
        if is_required and not value:
            while not value:
                self.log(f'{field_name.replace("_", " ").title()} is required', 'ERROR')
                value = input(prompt).strip()
        
        return value if value else default_value
    
    def _handle_list_field(self, field_name: str, item_type: Any, context: str) -> List[Any]:
        """Handle list fields by asking if user wants to add items."""
        
        items = []
        item_type_name = getattr(item_type, '__name__', str(item_type)).replace('Config', '').lower()
        
        add_items = input(f'\nDo you want to add {item_type_name}s to this {context}? (y/n): ').strip().lower()
        
        if add_items == 'y':
            item_count = 1
            while True:
                self.log(f'\n--- Adding {item_type_name} #{item_count} ---')
                
                # If it's a Pydantic model, use recursive building
                if inspect.isclass(item_type) and issubclass(item_type, BaseModel):
                    item_data = self.get_model_data_interactive(item_type, item_type_name)
                    items.append(item_data)
                else:
                    # Handle simple types in lists
                    value = input(f'Enter {item_type_name} value: ').strip()
                    if value:
                        items.append(value)
                
                # Ask if they want to add more
                add_more = input(f'\nAdd another {item_type_name}? (y/n): ').strip().lower()
                if add_more != 'y':
                    break
                
                item_count += 1
        
        return items
    
    def _handle_dict_field(self, field_name: str, args: tuple, context: str) -> Dict[str, Any]:
        """Handle dictionary fields by asking for key-value pairs in a loop."""
        
        data = {}
        
        add_items = input(f'\nDo you want to add items to {field_name}? (y/n): ').strip().lower()
        
        if add_items == 'y':
            while True:
                key = input('Enter key (or press Enter to finish): ').strip()
                if not key:
                    break
                
                value = input(f'Enter value for "{key}": ').strip()
                
                # Try to convert value to appropriate type if possible
                if value.lower() in ['true', 'false']:
                    value = value.lower() == 'true'
                elif value.isdigit():
                    value = int(value)
                elif value.replace('.', '').isdigit():
                    value = float(value)
                
                data[key] = value
        
        return data
    
    def _handle_nested_model_field(self, field_name: str, field_type: type[BaseModel], is_required: bool, context: str) -> Dict[str, Any]:
        """Handle nested Pydantic model fields."""
        
        model_name = field_type.__name__.replace('Config', '').lower()
        
        if is_required:
            self.log(f'\n{field_name.replace("_", " ").title()} is required.')
            return self.get_model_data_interactive(field_type, model_name)
        else:
            add_nested = input(f'\nDo you want to configure {field_name.replace("_", " ")}? (y/n): ').strip().lower()
            if add_nested == 'y':
                return self.get_model_data_interactive(field_type, model_name)
        
        return None
