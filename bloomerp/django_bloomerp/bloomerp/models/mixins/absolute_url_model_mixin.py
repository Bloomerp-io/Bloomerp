from django.db import models
from django.urls import reverse


class AbsoluteUrlModelMixin(models.Model):
    """
    A mixin for models that need to have an absolute URL.
    """
    class Meta:
        abstract = True

    def get_absolute_url(self):
        """
        Returns the absolute URL of the model instance.
        """
        return reverse(f'{self._meta.verbose_name_plural.replace(' ','_')}_detail_overview'.lower(), kwargs={'pk': self.pk})