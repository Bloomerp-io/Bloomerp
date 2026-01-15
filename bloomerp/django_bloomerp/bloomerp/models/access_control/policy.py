from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.mixins import TimestampedModelMixin, UserStampedModelMixin

class Policy(
    TimestampedModelMixin,
    UserStampedModelMixin,
    models.Model):
    """
    Represents an access control policy, which combines row-level and field-level policies.
    """
    name = models.CharField(
            max_length=255,
            help_text=_("The name of the access control policy.")
        )
    
    description = models.TextField(
        blank=True,
        help_text=_("A description of the access control policy.")
    )
    
    row_policy = models.ForeignKey(
        to=RowPolicy,
        on_delete=models.CASCADE,
        related_name='policies',
        help_text=_("The row-level policy associated with this access control policy.")
    )
    
    field_policy = models.ForeignKey(
        to=FieldPolicy,
        on_delete=models.CASCADE,
        related_name='policies',
        help_text=_("The field-level policy associated with this access control policy.")
    )
    
    
    
    
    