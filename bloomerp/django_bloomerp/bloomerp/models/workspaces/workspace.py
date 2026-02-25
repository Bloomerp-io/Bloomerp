from django.db import models
from django.conf import settings
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins import AbsoluteUrlModelMixin

class Workspace(AbsoluteUrlModelMixin, models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_workspace'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
        )
    name = models.CharField(
        max_length=255
        )
    sub_module_id = models.CharField(
        max_length=255
        )
    module_id = models.CharField(
        max_length=255
        )
    
    