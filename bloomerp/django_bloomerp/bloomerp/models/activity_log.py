from ast import mod
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db.models import QuerySet
from bloomerp.models.users.user import User


class ActivityLogManager(models.Manager):
    
    def for_object(self, obj: models.Model) -> QuerySet["ActivityLog"]:
        """
        Return activity logs for a specific object.
        
        Args:
            obj (models.Model): The object for which to retrieve activity logs.
        Returns:
            QuerySet[ActivityLog]: A queryset of activity logs related to the specified object.
        
        """
        content_type = ContentType.objects.get_for_model(obj)
        return self.filter(content_type=content_type, object_id=obj.pk)

    def for_user(self, user: User) -> QuerySet["ActivityLog"]:
        """Filters the activity logs for a specific user.
        
        Args:
            user (User): The user for whom to filter the activity logs.
        Returns:
            QuerySet[ActivityLog]: A queryset of activity logs for the specified user.
        """
        return self.filter(user=user)
    
    
class ActivityLog(models.Model):
    """
    Model to log activities performed by users.
    """
    class Meta:
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        ordering = ["-timestamp"]
        db_table = "bloomerp_activity_log"

    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    content_type = models.ForeignKey(to=ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255)
    object: models.Model = GenericForeignKey(
        ct_field="content_type", fk_field="object_id"
    )
    payload = models.JSONField(blank=True, null=True)

    # manager
    objects = ActivityLogManager()
