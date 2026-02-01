from django.test import TestCase


class TestAutomationModels(TestCase):
    def setUp(self):
        return super().setUp()
    
    
    def test_get_trigger(self):
        """
        Tests whether the trigger retrieving functionality for a model works.
        """