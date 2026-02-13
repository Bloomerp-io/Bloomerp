from django.db import models
from django.contrib.auth import get_user_model

from bloomerp.model_fields.icon_field import IconField

class SidebarItemManager(models.Manager):
    # Things 
    pass

class SidebarItem(models.Model):
    """
    A sidebar item
    """
    class Meta:
        db_table = "bloomerp_sidebar_item"

    user = models.ForeignKey(
        to= get_user_model()
    )
    name = models.CharField(
        max_length=255
    )
    icon = IconField()
    url = models.URLField()
    