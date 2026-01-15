from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType

class FieldPolicy(models.Model):
    """
    Represents a field-level access control policy.
    
    Example of a JSON rule:
    ```python
    # 1: the application_field_id
    # 123, 124, 125: the permission id's
    
    {
        1 : [123, 124, 125]
    }
    ```
    
    """
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
    )
    
    name = models.CharField(
            max_length=255,
            help_text=_("The name of the field-level access control policy.")
        )
    
    description = models.TextField(
        blank=True,
        help_text=_("A description of the field-level access control policy.")
    )
    
    rule = models.JSONField(
        help_text=_("A JSON representation of the field-level access control rules.")
    )
    
    



