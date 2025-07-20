from django.db import models
from bloomerp.models.core import BloomerpModel
# Test models required in test cases
# 1. Normal model with most of the fields
# 2. Foreign key relation ship

class DefaultTestModel(BloomerpModel):
    char_field = models.CharField(max_length=255)
    int_field = models.CharField()

class ForeignTestModel(BloomerpModel):
    char_field = models.CharField(max_length=250)
    fk_field = models.ForeignKey(DefaultTestModel, on_delete=models.CASCADE, null=True, blank=True)


TEST_MODELS = [
    DefaultTestModel,
    ForeignTestModel
]