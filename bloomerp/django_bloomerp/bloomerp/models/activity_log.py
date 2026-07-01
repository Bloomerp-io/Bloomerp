from ast import mod
from typing import Any
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from pydantic import BaseModel
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.user import User
    
    
class ActivityLogSource(models.TextChoices):
    DETAIL = "DETAIL", "DETAIL"
    API = "API", "API"
    CREATE = "CREATE", "CREATE"
    BULK = "BULK", "BULK"    


class ActivityLogChange(BaseModel):
    field_name : str
    from_value : Any
    to_value : Any
    
class ActivityLogAction(models.TextChoices):
    CHANGE = "CHANGE", "Change"
    CREATE = "CREATE", "Create"
    DELETE = "DELETE", "Delete"
    

class ActivityLog(models.Model):
    """
    Model to log activities performed by users.
    """
    bloomerp_config = BloomerpModelConfig(
        allow_string_search=False,
    )

    class Meta:
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        ordering = ["-timestamp"]
        db_table = "bloomerp_activity_log"

    timestamp = models.DateTimeField(
        auto_now_add=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE
    )
    object_id = models.CharField(
        max_length=255
    )
    object: models.Model = GenericForeignKey(
        ct_field="content_type", fk_field="object_id"
    )
    payload = models.JSONField(
        blank=True, 
        null=True
    )
    is_create = models.BooleanField(
        default=False
    )
    source = models.CharField(
        max_length=12,
        default=ActivityLogSource.DETAIL.value
    )
    action = models.CharField(
        max_length=12,
        choices=ActivityLogAction.choices,
        default=ActivityLogAction.CHANGE
    )

    @property
    def summary_string(self) -> str:
        action = ActivityLogAction(self.action)
        actor = self.actor or "System"
        
        match action:
            case ActivityLogAction.DELETE:
                return f"{actor} deleted this object"    
            case ActivityLogAction.CHANGE:
                if isinstance(self.payload, list):
                    fields: list[str] = []
                    first_to_value: Any = None
                    for change in self.payload:
                        if not isinstance(change, dict):
                            continue
                        field_name = change.get("field") or change.get("field_name")
                        if field_name:
                            fields.append("'" + str(field_name) + "'")
                            if len(fields) == 1:
                                first_to_value = change.get("to")

                    if not fields:
                        return f"{actor} changed the object"

                    if len(fields) == 1:
                        return f"{actor} changed the field {fields[0]} to {first_to_value}"

                    if len(fields) == 2:
                        return f"{actor} changed the fields {fields[0]} and {fields[1]}"
                    
                    return f"{actor} changed the fields {fields[0]}, {fields[1]} and more"
                
                return f"{actor} changed the object"
                
            case ActivityLogAction.CREATE:
                return f"{actor} created this object"
            
        return f"{actor} changed the object"
        