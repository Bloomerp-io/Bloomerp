from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.base_bloomerp_model import BloomerpModel


class UserDetailViewPreference(models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_user_detail_view_preference'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name = 'detail_view_preference'
        )
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE
        )
    
    field_layout = models.JSONField(
        default=dict
    )
    
    
    
