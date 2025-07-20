from django.test import TransactionTestCase
from django.db import models
from django.apps import apps
from django.db import connection

from bloomerp.constants.test_models import TEST_MODELS

class BaseBloomerpTestCase(TransactionTestCase):
    app_label = "bloomerp"

    def setUp(self):
        # Register the model with the app registry
        for model in TEST_MODELS:
            apps.register_model(self.app_label, model)
        
            # Create the table in the test database
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(model)

        self.extendedSetup()
        return super().setUp()
    
    def tearDown(self):
        # Drop the table after the test
        with connection.schema_editor() as schema_editor:
            for model in TEST_MODELS:
                schema_editor.delete_model(model)
        
        # Unregister the model
        del apps.all_models[self.app_label]['testmodel']

    def extendedSetup(self):
        pass


    
