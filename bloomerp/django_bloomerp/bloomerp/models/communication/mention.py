from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from bloomerp.model_fields.user_field import UserField
from bloomerp.models.base_bloomerp_model import BloomerpModel

class Mention(models.Model):
    """
    A model that stores mentions to users in particular pieces of content.
    An example of a mention 
    
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_mention'
        
    content_type = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        help_text=_("The content type (model) this field belongs to.")
        )
    object_id = models.CharField(
        max_length=255
    )
    user = UserField(
        on_delete=models.CASCADE,
        null=False,
        blank=False
    )