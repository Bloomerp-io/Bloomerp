from bloomerp.model_fields.user_field import UserField


from django.db import models


class UserStampModelMixin(models.Model):
    """
    A mixin for models that need to be stamped with the user that created or updated them.
    """
    created_by = UserField(
        on_delete=models.SET_NULL,
        related_name='%(class)s_created',
        null=True)
    updated_by = UserField(
        on_delete=models.SET_NULL,
        related_name='%(class)s_updated',
        null=True)

    class Meta:
        abstract = True