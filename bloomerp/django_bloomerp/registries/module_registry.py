from bloomerp.modules.definition import ModuleConfig
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ModuleRegistry:
    """
    A registry for managing module configurations in the Bloomerp system.
    Provides functionality to register, retrieve, and manage modules.
    """
    
    def __init__(self):
        self.items: Dict[str, ModuleConfig] = {}
    
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


# Global registry instance
registry = ModuleRegistry()