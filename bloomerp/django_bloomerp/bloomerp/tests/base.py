from django.test import TransactionTestCase, modify_settings
from django.db import models
from django.apps import apps
from django.db import connection
from django.urls import clear_url_caches
from bloomerp.management.commands import save_application_fields
from bloomerp.tests.utils.users import create_admin, create_normal_user
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.tests.utils.names import FIRST_NAMES, LAST_NAMES

@modify_settings(INSTALLED_APPS={'remove': 'bloomerp_modules'})
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

        # Collect dynamically created test models
        _test_models = [cls.CustomerModel]
        if cls.create_foreign_models:
            _test_models.extend([cls.CountryModel, cls.PlanetModel])

        # Register dynamic models in the module registry and router, then
        # reload the bloomerp URL patterns so that get_absolute_url() works.
        cls._register_dynamic_model_routes(_test_models)

    @classmethod
    def _register_dynamic_model_routes(cls, test_models: list) -> None:
        """
        Register routes for dynamically created test models.

        After models are created in ``setUpClass`` they are unknown to the
        router (which already ran ``models="__all__"`` expansion at import
        time).  This helper:

        1. Re-scans the module registry so test models are mapped to modules.
        2. Uses the stored route templates in the router to create equivalent
           routes for each new model.
        3. Appends the resulting URL patterns to ``bloomerp.urls.urlpatterns``
           and clears Django's URL resolver cache so the test client can
           resolve those URLs.
        """
        from bloomerp.modules.definition import module_registry
        from bloomerp.router import router, ViewType
        import bloomerp.urls as bloomerp_urls
        from django.urls import path as django_path

        # Re-scan so model→module mappings include the new test models
        module_registry._register_models_from_apps()

        # Register router routes for each test model
        for model in test_models:
            router.register_routes_for_model(model)

        # Append new URL patterns to bloomerp.urls.urlpatterns so they are
        # picked up by Django's URL resolver after clearing its cache.
        existing_names = {
            p.name
            for p in bloomerp_urls.urlpatterns
            if hasattr(p, 'name') and p.name
        }
        for route in router.routes:
            if route.model not in test_models:
                continue
            if route.url_name in existing_names:
                continue

            args = dict(route.args) if route.args else {}
            if route.model:
                args["model"] = route.model
            if route.module:
                args["module"] = route.module

            if route.view_type == ViewType.CLASS:
                pattern = django_path(
                    route.path.lstrip('/'),
                    route.view.as_view(**args),
                    name=route.url_name,
                )
            else:
                pattern = django_path(
                    route.path.lstrip('/'),
                    route.view,
                    name=route.url_name,
                    kwargs=args,
                )
            bloomerp_urls.urlpatterns.append(pattern)
            existing_names.add(route.url_name)

        clear_url_caches()
        
        
    def setUp(self):
        super().setUp()
        # Create application fields
        save_application_fields.Command().handle()
        
        # Create users
        if self.auto_create_users:
            self.admin_user = create_admin()
            self.normal_user = create_normal_user()
            # Log in as admin by default so test client requests are authenticated
        
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
        
    
    def create_customer(self, first_name:str, last_name:str, age:int, **kwargs) -> models.Model:
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
            age=age,
            **kwargs
        )
    
    def create_country(self, name:str, planet=None) -> models.Model:
        """Helper method to create countries

        Args:
            name (str): the name of the country
            planet (Planet, optional): the planet the country is located on. Defaults to None.

        Returns:
            Country: the created country object
        """
        if not self.create_foreign_models:
            raise Exception("Foreign models not enabled for this test case")
        
        return self.CountryModel.objects.create(
            name=name,
            planet=planet
        )
    

    def create_planet(self, name:str) -> models.Model:
        """Helper method to create planets

        Args:
            name (str): the name of the planet

        Returns:
            Planet: the created planet object
        """
        if not self.create_foreign_models:
            raise Exception("Foreign models not enabled for this test case")
        
        return self.PlanetModel.objects.create(
            name=name
        )
    
    