from django.utils.translation import gettext_lazy as _
from ast import mod
from typing import Any
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from pydantic import BaseModel
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig, StringSearchSettings
from bloomerp.models.users.user import User
    
    
class ActivityLogSource(models.TextChoices):
    DETAIL = "DETAIL", _("Detail")
    API = "API", _("API")
    CREATE = "CREATE", _("Create")
    BULK = "BULK", _("Bulk")


class ActivityLogChange(BaseModel):
    field_name : str
    from_value : Any
    to_value : Any
    
class ActivityLogAction(models.TextChoices):
    CHANGE = "CHANGE", _("Change")
    CREATE = "CREATE", _("Create")
    DELETE = "DELETE", _("Delete")
    

class ActivityLog(models.Model):
    """
    Model to log activities performed by users.
    """
    bloomerp_config = BloomerpModelConfig(
        string_search_settings=StringSearchSettings(
            allow_global_search=False,
        ),
        activity_log_settings=ActivityLogSettings(enabled=False)
    )

    class Meta:
        verbose_name = _("Activity Log")
        verbose_name_plural = _("Activity Logs")
        ordering = ["-timestamp"]
        db_table = "bloomerp_activity_log"

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name=_("Actor"),
    )
    content_type = models.ForeignKey(
        to=ContentType, 
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
    )
    object_id = models.CharField(
        max_length=255,
        verbose_name=_("Object ID"),
    )
    object: models.Model = GenericForeignKey(
        ct_field="content_type", fk_field="object_id"
    )
    payload = models.JSONField(
        blank=True, 
        null=True,
        verbose_name=_("Payload"),
    )
    is_create = models.BooleanField(
        default=False,
        verbose_name=_("Is Create"),
    )
    source = models.CharField(
        max_length=12,
        choices=ActivityLogSource.choices,
        default=ActivityLogSource.DETAIL.value,
        verbose_name=_("Source"),
    )
    action = models.CharField(
        max_length=12,
        choices=ActivityLogAction.choices,
        default=ActivityLogAction.CHANGE,
        verbose_name=_("Action"),
    )

    @property
    def summary_string(self) -> str:
        """Describe the recorded action and its changed fields for the activity feed."""
        action = ActivityLogAction(self.action)
        actor = self.actor or _("System")
        
        match action:
            case ActivityLogAction.DELETE:
                return _("%(actor)s deleted this object") % {"actor": actor}
            case ActivityLogAction.CHANGE:
                if isinstance(self.payload, list):
                    fields: list[str] = []
                    first_to_value: Any = None
                    first_has_to_value = False
                    for change in self.payload:
                        if not isinstance(change, dict):
                            continue
                        field_name = change.get("field") or change.get("field_name")
                        if field_name:
                            fields.append("'" + str(field_name) + "'")
                            if len(fields) == 1:
                                first_has_to_value = "to" in change
                                first_to_value = change.get("to")

                    if not fields:
                        return _("%(actor)s changed the object") % {"actor": actor}

                    if len(fields) == 1:
                        if not first_has_to_value:
                            return _("%(actor)s changed the field %(field)s") % {
                                "actor": actor,
                                "field": fields[0],
                            }
                        return _("%(actor)s changed the field %(field)s to %(value)s") % {
                            "actor": actor,
                            "field": fields[0],
                            "value": first_to_value,
                        }

                    if len(fields) == 2:
                        return _("%(actor)s changed the fields %(first)s and %(second)s") % {
                            "actor": actor,
                            "first": fields[0],
                            "second": fields[1],
                        }
                    
                    return _("%(actor)s changed the fields %(first)s, %(second)s and more") % {
                        "actor": actor,
                        "first": fields[0],
                        "second": fields[1],
                    }
                
                return _("%(actor)s changed the object") % {"actor": actor}
                
            case ActivityLogAction.CREATE:
                return _("%(actor)s created this object") % {"actor": actor}
            
        return _("%(actor)s changed the object") % {"actor": actor}
        
