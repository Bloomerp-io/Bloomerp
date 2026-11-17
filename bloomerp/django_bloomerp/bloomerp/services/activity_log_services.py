import json
from collections.abc import Callable
from typing import Any, Optional, Type

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model, QuerySet
from django.http import HttpRequest

from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction, ActivityLogSource
from bloomerp.models.definition import ActivityLogContext, ActivityLogDecision, get_model_config
from bloomerp.models.users.user import User
from bloomerp.serializers.model_serializers import get_serializer_cls


class ActivityLogManager:
    payload: Any
    
    def __init__(
        self, instance: Model, request: HttpRequest | None = None, *, using: str | None = None
    ) -> None:
        """Prepare to log a model operation on its database connection."""
        self.instance = instance
        self.request = request
        self.using = using or instance._state.db
        self.payload = []
        self._snapshot_fields: frozenset[str] | None = None
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
        
    
    def _get_record_policy(
        self,
    ) -> Callable[[ActivityLogContext], ActivityLogDecision] | None:
        """Return the optional logging callback declared by the model."""
        config = get_model_config(self.get_model_cls())
        return config.activity_log_settings.should_record if config else None

    def _apply_record_policy(
        self,
        policy: Callable[[ActivityLogContext], ActivityLogDecision],
        changed_fields: frozenset[str],
    ) -> bool:
        """Keep changed field names and defer reading snapshot values until needed."""
        decision = policy(
            ActivityLogContext(
                action=self.action,
                instance=self.instance,
                actor=self.get_actor(),
                changed_fields=changed_fields,
            )
        )
        if not decision.record:
            return False
        self._snapshot_fields = decision.snapshot_fields
        self.payload = [{"field": name} for name in sorted(changed_fields)]
        return True

    def set_changes(self, update_fields: frozenset[str] | None = None) -> bool:
        """Prepare an activity entry for the pending save if its policy allows it."""
        policy = self._get_record_policy()
        before_instance = None
        if self.instance.pk and (policy is None or not self.is_create):
            model = self.get_model_cls()
            manager = model.objects if policy is None else model._base_manager
            before_instance = manager.using(self.using).filter(pk=self.instance.pk).first()

        if policy is not None:
            changed_fields = frozenset(
                field.name
                for field in self.instance._meta.concrete_fields
                if field.attname in self.instance.__dict__
                and (
                    update_fields is None
                    or field.name in update_fields
                    or field.attname in update_fields
                )
                and (
                    before_instance is None
                    or getattr(before_instance, field.attname) != getattr(self.instance, field.attname)
                )
            )
            return self._apply_record_policy(policy, changed_fields)

        before_data = self._serialize_instance(before_instance)
        after_data = self._serialize_instance(self.instance)
        self.payload = self._build_changes(before_data=before_data, after_data=after_data)
        return True

    def _payload_with_snapshot(self) -> list[dict[str, Any]]:
        """Capture the selected persisted values as a single snapshot in the payload."""
        if not self._snapshot_fields:
            return self.payload
        snapshot = self.get_model_cls()._base_manager.using(self.using).values(
            *sorted(self._snapshot_fields)
        ).get(pk=self.instance.pk)
        return [{"snapshot": snapshot}, *self.payload]

    def set_delete(self) -> bool:
        """Prepare an activity entry and capture any selected values before deletion."""
        self.action = ActivityLogAction.DELETE
        policy = self._get_record_policy()
        if policy is None:
            self.payload = self._make_json_safe(self._serialize_instance(self.instance))
            return True
        if not self._apply_record_policy(policy, frozenset()):
            return False
        self.payload = self._payload_with_snapshot()
        return True

    def get_content_type(self) -> ContentType:
        """Return the content type on the same database as the logged operation."""
        return ContentType.objects.db_manager(self.using).get_for_model(self.get_model_cls())

    def persist(self) -> ActivityLog | None:
        """Write the prepared event and any post-save snapshot on its database."""
        if (
            self.action == ActivityLogAction.CHANGE
            and not self.payload
            and self._snapshot_fields is None
        ):
            return None

        payload = self.payload if self.action == ActivityLogAction.DELETE else self._payload_with_snapshot()
        return ActivityLog.objects.using(self.using).create(
            actor=self.get_actor(),
            is_create=self.is_create,
            payload=self._make_json_safe(payload),
            source=self.get_activity_log_source(),
            content_type=self.get_content_type(),
            object_id=str(self.instance.pk),
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
        """Return the authenticated request user if the operation has one."""
        user = getattr(self.request, "user", None)
        return user if user is not None and user.is_authenticated else None

    def get_for_object(self) -> QuerySet[ActivityLog]:
        """Find activity entries for this instance on its database."""
        return ActivityLog.objects.using(self.using).filter(
            object_id=str(self.instance.pk),
            content_type=self.get_content_type()
        )
        
    @staticmethod
    def should_record_change(model: type[Model]) -> bool:
        """Return whether activity logging is enabled for this model."""
        config = get_model_config(model)
        return config is not None and config.activity_log_settings.enabled
    
