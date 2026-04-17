from django.db import models


class TimestampModelMixin(models.Model):
    """
    A mixin for models that need to be timestamped.
    """
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True