"""Shared persistence invariants for private agent models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, router, transaction

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    StringSearchSettings,
)
from bloomerp.modules.bloomai import BloomAIModule

from .fields import AgentJSONField


class AgentQuerySet(models.QuerySet):
    """Require validated instance saves for cross-row and immutable invariants."""

    def update(self, **kwargs: Any) -> int:
        """Reject updates that bypass validation and immutable proposal checks."""
        raise TypeError(
            "Agent models require validated instance.save(); QuerySet.update is unsupported"
        )

    def bulk_create(
        self, objs: Iterable[models.Model], *args: Any, **kwargs: Any
    ) -> list[models.Model]:
        """Reject bulk inserts until a validated batch persistence service exists."""
        raise TypeError(
            "Agent models require validated instance.save(); bulk_create is unsupported"
        )

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        *args: Any,
        **kwargs: Any,
    ) -> int:
        """Reject bulk writes that bypass per-record invariants."""
        raise TypeError(
            "Agent models require validated instance.save(); bulk_update is unsupported"
        )


class AgentModel(BloomerpModel):
    """Keep agent records private and validate writes under a per-record lock."""

    objects = AgentQuerySet.as_manager()
    avatar = None
    immutable_fields: ClassVar[tuple[str, ...]] = ()
    bloomerp_config = BloomerpModelConfig(
        module=BloomAIModule,
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        string_search_settings=StringSearchSettings(allow_global_search=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )
    
    class Meta(BloomerpModel.Meta):
        abstract = True

    def clean(self) -> None:
        """Normalize all JSON payloads, including blank containers Django skips."""
        super().clean()
        errors: dict[str, Any] = {}
        for field in self._meta.fields:
            if isinstance(field, AgentJSONField):
                try:
                    setattr(
                        self,
                        field.attname,
                        field.normalize(getattr(self, field.attname)),
                    )
                except ValidationError as exc:
                    errors[field.name] = exc.messages
        if errors:
            raise ValidationError(errors)

    def check_conversation(
        self, field_name: str, conversation_id: Any, expected_id: Any
    ) -> None:
        """Reject a provenance link pointing outside the owning conversation."""
        if conversation_id != expected_id:
            raise ValidationError(
                {field_name: "Related record must belong to the same conversation."}
            )

    def immutable_fields_for(self, old: AgentModel) -> tuple[str, ...]:
        """Return fields frozen after the first successful save."""
        return self.immutable_fields

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate state and prevent immutable changes while locking existing rows."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            old = None
            if not self._state.adding:
                old = (
                    type(self)
                    .objects.using(database)
                    .select_for_update()
                    .filter(pk=self.pk)
                    .first()
                )
            self.full_clean()
            if old is not None:
                for field in self.immutable_fields_for(old):
                    if getattr(old, field) != getattr(self, field):
                        raise ValidationError(
                            {
                                field: "This value is immutable; create a new record or revision."
                            }
                        )
            super().save(*args, **kwargs)
