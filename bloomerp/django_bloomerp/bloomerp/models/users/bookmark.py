from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.translation import gettext as _
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.utils.models import get_detail_view_url
from django.conf import settings
from django.urls import reverse

class Bookmark(models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = "bloomerp_bookmark"
    
    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
        )
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE
        )
    object_id = models.PositiveIntegerField()
    object : models.Model = GenericForeignKey(
        ct_field="content_type", 
        fk_field="object_id"
        )
    datetime_created = models.DateTimeField(
        auto_now_add=True
        )

    allow_string_search = False

    def __str__(self) -> str:
        return f"Bookmark for {self.content_type} with ID {self.object_id}"

    def get_absolute_url(self):
        try:
            return self.object.get_absolute_url()
        except:
            model = self.object._meta.model
            detail_view_url = get_detail_view_url(model)
            return reverse(detail_view_url, args=[self.object.pk])