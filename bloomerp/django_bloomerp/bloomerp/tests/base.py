from django.test import TransactionTestCase
from django.db import models
from django.apps import apps
from django.db import connection
from bloomerp.management.commands import save_application_fields
from bloomerp.tests.utils.users import create_admin, create_normal_user
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.tests.utils.names import FIRST_NAMES, LAST_NAMES

class BaseBloomerpModelTestCase(TransactionTestCase):
    auto_create_customers = True
    auto_create_users = True
    
    create_foreign_models = False
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        if cls.create_foreign_models:
            foreign_models = create_test_models(
                app_label="bloomerp",
                model_defs={
                    "Planet" : {
                        "name" : models.CharField(max_length=100)
                    },
                    "Country" : {
                        "name"  : models.CharField(max_length=100),
                        "planet" : models.ForeignKey(to="Planet", on_delete=models.CASCADE)
                    },
                    
                }
            )
             
            cls.CountryModel = foreign_models["Country"]
            cls.PlanetModel = foreign_models["Planet"]
            
            
        
        customer_def = {
            "first_name": models.CharField(max_length=100),
            "last_name": models.CharField(max_length=100),
            "age" : models.IntegerField(max_length=3),
        }
        
        if cls.create_foreign_models:
            customer_def["country"] = models.ForeignKey(
                to=cls.CountryModel, 
                blank=True, 
                null=True,
                on_delete=models.SET_NULL
                )
        
        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": customer_def
            },
            use_bloomerp_base=True,
        )["Customer"]
        
        
    def setUp(self):
        super().setUp()
        # Create application fields
        save_application_fields.Command().handle()
        
        # Create users
        if self.auto_create_users:
            self.admin_user = create_admin()
            self.normal_user = create_normal_user()
        
        if self.create_foreign_models:
            for i in ["Earth", "Mars"]:
                self.PlanetModel.objects.create(
                    name=i
                )
            
            for i in ["Belgium", "Netherlands", "Brazil"]:
                self.CountryModel.objects.create(
                    name=i,
                    planet=self.PlanetModel.objects.filter(name="Earth").first()
                )
                
            for i in ["Helvetia", "Aresia"]:
                self.CountryModel.objects.create(
                    name=i,
                    planet=self.PlanetModel.objects.filter(name="Mars").first()
                )
            
        # Create customer objects
        if self.auto_create_customers:
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
        
    
    def create_customer(self, first_name:str, last_name:str, age:int):
        """Helper method to create customers

        Args:
            first_name (str): the first name of the customer
            last_name (str): the last name of the customer
            age (int): the age of the customer

        Returns:
            Customer: the created customer object
        """
        return self.CustomerModel.objects.create(
            first_name=first_name,
            last_name=last_name,
            age=age
        )
    

    