from django.test import TransactionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models
from bloomerp.modules.definition import module_registry

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
            bloomerp_meta_class=None, # Should be added to 'misc' modules
        )["Customer"]
        
        # Create meta class
        class OrderBloomerpMeta:
            modules = ["data"]
        
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
            bloomerp_meta_class=OrderBloomerpMeta # Should be added to 'data' module
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
    