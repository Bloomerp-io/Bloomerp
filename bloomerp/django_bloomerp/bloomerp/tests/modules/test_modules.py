from django.test import TransactionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models
from bloomerp.modules.definition import BloomerpModule, module_registry
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.modules.users import UsersModule

class TestModules(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100),
                }
            },
            use_bloomerp_base=True,
            bloomerp_config=None, # Should be added to 'misc' module
        )["Customer"]

        cls.OrderModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Order": {
                    "order_number": models.CharField(max_length=100),
                    "customer": models.ForeignKey(
                        cls.CustomerModel, 
                        on_delete=models.CASCADE,
                        related_name="orders"
                    ),
                }
            },
            use_bloomerp_base=True,
            bloomerp_config=BloomerpModelConfig(module="data"), # Should be added to 'data' module
        )["Order"]
        
        module_registry.refresh()
         
    def test_model_automatically_assigned_to_misc_module(self):
        """Tests whether a model without module specification is assigned to 'misc' module."""
        models = module_registry.get_models_for_module("misc")
        
        # Check if CustomerModel is in misc module
        self.assertIn(
            self.CustomerModel, 
            models, 
        )
        
    def test_model_assigned_to_specified_module(self):
        """Tests whether a model with module specification is assigned to the correct module."""
        models = module_registry.get_models_for_module("data")
        
        # Check if OrderModel is in data module
        self.assertIn(
            self.OrderModel, 
            models, 
        )
    
    def test_get_module_for_model(self):
        """Tests whether get_module_for_model returns the correct module for a given model."""
        customer_module = module_registry.get_module_for_model(self.CustomerModel)
        order_module = module_registry.get_module_for_model(self.OrderModel)
        
        # Check if CustomerModel is in misc module
        self.assertIsNotNone(customer_module)
        self.assertEqual(customer_module.id, "misc")
        
        # Check if OrderModel is in data module
        self.assertIsNotNone(order_module)
        self.assertEqual(order_module.id, "data")

    def test_module_subclass_allows_plain_class_attributes(self):
        """Module subclasses should not need repeated type annotations."""

        class PlainModule(BloomerpModule):
            id = "plain"
            name = "Plain"
            code = "plain"

        module = PlainModule.to_config()

        self.assertEqual(module.id, "plain")
        self.assertEqual(module.name, "Plain")
        self.assertEqual(module.code, "plain")

    def test_bloomerp_model_config_accepts_module_class(self):
        """Model config can reference a module authoring class directly."""
        config = BloomerpModelConfig(module=UsersModule)

        self.assertEqual(config.module, "users")
