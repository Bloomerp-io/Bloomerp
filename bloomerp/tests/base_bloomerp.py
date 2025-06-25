from django.test import TestCase
from django.db import models

class BaseBloomerpTestCase(TestCase):
    def setUp(self):
        # ----------------------------
        # Models: create models
        # ----------------------------
        class TestModel(models.Model):
            char_field = models.CharField(max_length=50)
        
        self.a_model = TestModel
        
        obj =TestModel.objects.create(char_field="Hey Man")
        self.a_obj = obj
        
        
        self.extendedSetUp()
        return super().setUp()
    
    def extendedSetUp(self):
        pass