import json
from typing import Any, Optional, Type

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model, QuerySet
from django.http import HttpRequest

from bloomerp.models.activity_log import ActivityLog, ActivityLogAction, ActivityLogSource
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.user import User
from bloomerp.serializers.model_serializers import get_serializer_cls
from django.contrib.contenttypes.models import ContentType


class ActivityLogManager:
    payload: Any
    
    def __init__(self, instance: Model, request: Optional[HttpRequest] = None):
        self.instance = instance
        self.request = request
        self.payload = []
        self.is_create = instance._state.adding
        self.action = ActivityLogAction.CREATE if self.is_create else ActivityLogAction.CHANGE
    
        
    def get_model_cls(self) -> Type[Model]:
        """Returns the model cls

        Returns:
            Type[Model]: the model cls
        """
        return self.instance._meta.model
        
    def _serialize_instance(self, instance: Optional[Model]) -> dict[str, Any]:
        if instance is None:
            return {}
        serializer_cls = get_serializer_cls(self.get_model_cls())
        return dict(serializer_cls(instance).data)

    def _make_json_safe(self, value: Any) -> Any:
        """Convert Django/Python scalar values into JSONField-safe values."""
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder))

    def _build_changes(self, before_data: dict[str, Any], after_data: dict[str, Any]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        all_fields = set(before_data.keys()) | set(after_data.keys())
        for field in sorted(all_fields):
            from_value = before_data.get(field)
            to_value = after_data.get(field)
            if from_value != to_value:
                changes.append(
                    {
                        "field": field,
                        "from": self._make_json_safe(from_value),
                        "to": self._make_json_safe(to_value),
                    }
                )
        return changes

    def set_changes(self) -> None:
        """Compute field-level changes using serialized before/after snapshots."""
        before_instance: Optional[Model] = None
        if self.instance.pk:
            before_instance = self.get_model_cls().objects.filter(pk=self.instance.pk).first()

        before_data = self._serialize_instance(before_instance)
        after_data = self._serialize_instance(self.instance)
        self.payload = self._build_changes(before_data=before_data, after_data=after_data)
    
    def set_delete(self) -> None:
        """Capture a full JSON-safe representation before the object is deleted."""
        self.action = ActivityLogAction.DELETE
        self.payload = self._make_json_safe(self._serialize_instance(self.instance))
    
    def get_content_type(self):
        return ContentType.objects.get_for_model(self.get_model_cls())
        
    def persist(self):
        """Persists the activity log"""
        if self.action == ActivityLogAction.CHANGE and len(self.payload) == 0:
            return None

        return ActivityLog.objects.create(
            actor=self.get_actor(),
            is_create=self.is_create,
            payload=self._make_json_safe(self.payload),
            source=self.get_activity_log_source(),
            content_type=self.get_content_type(),
            object_id=str(self.instance.id),
            action=self.action,
        )
             
    def get_activity_log_source(self) -> ActivityLogSource:
        """Returns the activity log source

        Returns:
            ActivityLogSource: _description_
        """
        if self.request:
            if "/create/" in self.request.path:
                return ActivityLogSource.CREATE
            if "/api/" in self.request.path:
                return ActivityLogSource.API
            if "/bulk-upload/" or "/import/" in self.request.path:
                return ActivityLogSource.BULK
            
        return ActivityLogSource.DETAIL
       
    def get_actor(self) -> Optional[User]:
        """Returns the user/actor related to the change

        Returns:
            User: the user object
        """
        if self.request is None:
            return None
        return self.request.user
    
    def get_for_object(self) -> QuerySet[ActivityLog]:
        return ActivityLog.objects.filter(
            object_id=str(self.instance.id),
            content_type=self.get_content_type()
        )

    @staticmethod
    def should_record_change(model:Type[Model]) -> bool:
        """Whether a change should be recorded on this instance

        Returns:
            bool: 
        """
        
        if not hasattr(model, "bloomerp_config"):
            return False
        
        config = getattr(model, "bloomerp_config")
        
        if not isinstance(config, BloomerpModelConfig):
            return False
        
        return config.record_activity_log
    
