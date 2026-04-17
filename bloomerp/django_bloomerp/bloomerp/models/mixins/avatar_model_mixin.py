from django.db import models


class AvatarModelMixin(models.Model):
    """
    A mixin for models that need to have an avatar.
    """
    class Meta:
        abstract = True
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)