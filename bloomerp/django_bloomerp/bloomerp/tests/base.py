from django.test import TransactionTestCase
from django.db import models
from django.apps import apps
from django.db import connection
from bloomerp.management.commands import save_application_fields
from bloomerp.tests.utils.users import create_admin, create_normal_user
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.tests.utils.names import FIRST_NAMES, LAST_NAMES

class BaseBloomerpModelTestCase(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100),
                    "age" : models.IntegerField(max_length=3)
                }
            },
            use_bloomerp_base=True
        )["Customer"]
        
        
    
    def setUp(self):
        super().setUp()
        # Create application fields
        save_application_fields.Command().handle()
        
        # Create users
        self.admin_user = create_admin()
        self.normal_user = create_normal_user()
        
        # Create customer objects
        for i in range(10):
            self.CustomerModel.objects.create(
                first_name = FIRST_NAMES[i],
                last_name = LAST_NAMES[i],
                age = 20 + i
            )
        
        # Call extended setup
        self.extendedSetup()
        
    def extendedSetup(self):
        pass
        
        
