import json
import logging
from typing import Any, Optional, Type

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model, QuerySet
from django.http import HttpRequest

from bloomerp.filters.compiler import resolve_condition
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.models.audit.activity_log import (
    ActivityLog,
    ActivityLogAction,
    ActivityLogSource,
)
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig
from bloomerp.models.users.user import User
from bloomerp.serializers.model_serializers import get_serializer_cls

logger = logging.getLogger(__name__)


class ActivityLogManager:
    payload: Any
    
    def __init__(self, instance: Model, request: HttpRequest | None = None) -> None:
        """Capture the object and action before persistence changes its state."""
        self._conditions_match: bool | None = None
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

    def set_user_stamp(self) -> None:
        """
        Set's the user stamp of the object.
        """
        user = getattr(self.request, "user", None)
        if user is None:
            return

        if self.is_create and hasattr(self.instance, "created_by") and not user.is_anonymous:
            setattr(self.instance, "created_by", user)
            
        if hasattr(self.instance, "updated_by") and not user.is_anonymous:
            setattr(self.instance, "updated_by", user)
        
    
    def set_changes(self, update_fields: frozenset[str] | None = None) -> None:
        """Compute field-level changes using serialized before/after snapshots."""
        before_instance: Optional[Model] = None
        if self.instance.pk:
            before_instance = self.get_model_cls().objects.filter(pk=self.instance.pk).first()

        before_data = self._serialize_instance(before_instance)
        after_data = self._serialize_instance(self.instance)
        self.payload = self._build_changes(before_data=before_data, after_data=after_data)
        if update_fields is not None:
            saved_names = {
                field.name
                for field in self.instance._meta.concrete_fields
                if field.name in update_fields or field.attname in update_fields
            }
            self.payload = [change for change in self.payload if change["field"] in saved_names]
        self._conditions_match = self.matches_conditions(before_instance, update_fields)

        
        
    def set_delete(self) -> None:
        """Capture a full JSON-safe representation before the object is deleted."""
        self.action = ActivityLogAction.DELETE
        self.payload = self._make_json_safe(self._serialize_instance(self.instance))
        self._conditions_match = self.matches_conditions()
    
    def get_content_type(self):
        return ContentType.objects.get_for_model(self.get_model_cls())
        
    def get_settings(self) -> ActivityLogSettings:
        """Return configured audit gates, retaining defaults for direct manager users."""
        config = getattr(self.get_model_cls(), "bloomerp_config", None)
        return config.activity_log_settings if isinstance(config, BloomerpModelConfig) else ActivityLogSettings()

    def matches_conditions(
        self,
        before_instance: Model | None = None,
        update_fields: frozenset[str] | None = None,
    ) -> bool:
        """Evaluate shared filters on direct concrete values, with no relation traversal.

        Groups are ANDed; each group retains its AND/OR connector. Invalid
        configured predicates fail open to preserve the existing audit trail.
        """
        conditions = self.get_settings().conditions
        if not conditions:
            return True
        try:
            resolver = FilterFieldResolver.for_model(self.get_model_cls())
            group_matches = []
            for group in conditions:
                matches = []
                for condition in group.conditions:
                    field = self.instance._meta.get_field(condition.field_path)
                    if not field.concrete or field.many_to_many:
                        raise ValueError("Activity conditions require direct concrete fields")
                    if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
                        raise ValueError("Activity conditions do not support automatically generated timestamps")
                    if condition.lookup_id == "equals_user" and condition.value == "$user":
                        actor = self.get_actor()
                        if actor is None or not actor.is_authenticated or actor.pk is None:
                            raise ValueError("Current-user activity condition requires an authenticated actor")
                        condition = condition.model_copy(update={"value": actor.pk})
                    _resolved, _target, lookup, expected = resolve_condition(condition, resolver=resolver)
                    evaluator = lookup.get_python_evaluator()
                    if evaluator is None:
                        raise ValueError("Activity condition lookup has no Python evaluator")
                    source = self.instance
                    if (
                        before_instance is not None and update_fields is not None
                        and field.name not in update_fields and field.attname not in update_fields
                    ):
                        source = before_instance
                    matches.append(evaluator(getattr(source, field.attname), expected))
                group_matches.append(all(matches) if group.connector == "AND" else any(matches))
            return all(group_matches)
        except Exception:
            logger.exception("Invalid activity log conditions for %s; retaining audit entry", self.instance._meta.label)
            return True

    def persist(self) -> None:
        """Persist only events allowed by the model's value and actual-change gates."""
        settings = self.get_settings()
        if not settings.enabled:
            return
        if self.action == ActivityLogAction.CHANGE and not any(
            change["field"] not in settings.ignored_change_fields for change in self.payload
        ):
            return
        if self._conditions_match is None:
            self._conditions_match = self.matches_conditions()
        if not self._conditions_match:
            return
        actor = self.get_actor()
        ActivityLog.objects.create(
            actor=actor if actor is not None and not actor.is_anonymous else None,
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
            if "/bulk-upload/" in self.request.path or "/import/" in self.request.path:
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
        
        return config.activity_log_settings.enabled
    
