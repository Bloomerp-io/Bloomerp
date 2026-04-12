from bloomerp.models import TimestampedModelMixin
from bloomerp.models import UserStampedModelMixin
from bloomerp.models import BloomerpModel
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class Comment(
    TimestampedModelMixin,
    UserStampedModelMixin,
    models.Model,
):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_comment'

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=36) # In order to support both UUID and integer primary keys
    content_object = GenericForeignKey("content_type", "object_id")
    content = models.TextField()

    allow_string_search = False

    def __str__(self):
        return f"{self.content} - {self.created_by} - {self.datetime_created}"
