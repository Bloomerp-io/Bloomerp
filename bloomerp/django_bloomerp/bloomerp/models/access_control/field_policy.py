from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType

class FieldPolicy(models.Model):
    """
    Represents a field-level access control policy.
    
    Example of a JSON rule:
    ```python
    # 1: the application_field_id -> CODE
    # 123, 124, 125: the permission id's -> can_view, can_change, can_delete
    
    {
        1 : ["can_view", "can_change", "can_delete"],
        2 : ["can_view"],
        3 : ["can_view", "can_change"]
    }
    ```
    """
    class Meta:
        db_table = "bloomerp_access_control_field_policy"
        verbose_name = _("Access Control Field Policy")
        verbose_name_plural = _("Access Control Field Policies")
    
    content_type = models.ForeignKey(
        to=ContentType,
        on_delete=models.CASCADE,
    )
    
    name = models.CharField(
            max_length=255,
            help_text=_("The name of the field-level access control policy.")
        )
    
    rule = models.JSONField(
        help_text=_("A JSON representation of the field-level access control rules.")
    )
    
    def __str__(self):
        return f"{self.name} ({self.content_type.app_label}.{self.content_type.model})"
    
    



