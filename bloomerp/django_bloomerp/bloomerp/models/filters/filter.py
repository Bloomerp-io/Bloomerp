from django.db import models
from django.utils.translation import gettext as _
from bloomerp.models import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig

FILTER_CONFIG = BloomerpModelConfig()

class Filter(BloomerpModel):
    class Meta:
        db_table = "bloomerp_filter"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="bloomerp_model_unique_name",
            )
        ]

    bloomerp_config = FILTER_CONFIG

    name = models.CharField(max_length=255)
    
