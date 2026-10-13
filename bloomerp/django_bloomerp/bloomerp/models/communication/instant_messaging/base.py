"""Validated private persistence shared by the messaging models."""

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


class IMQuerySet(models.QuerySet):
    """Prevent bulk mutation from bypassing cross-conversation validation."""

    def update(self, **kwargs: Any) -> int:
        """Require validated instance saves for relation and credential updates."""
        raise TypeError(
            "IM models require instance.save(); QuerySet.update is unsupported."
        )

    def bulk_create(
        self, objs: Iterable[models.Model], *args: Any, **kwargs: Any
    ) -> list[models.Model]:
        """Require validation and encryption before each record is inserted."""
        raise TypeError(
            "IM models require instance.save(); bulk_create is unsupported."
        )

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        *args: Any,
        **kwargs: Any,
    ) -> int:
        """Require validated saves rather than bypassing cross-row invariants."""
        raise TypeError(
            "IM models require instance.save(); bulk_update is unsupported."
        )


class IMModel(BloomerpModel):
    """Keep messages private until explicitly authorized service endpoints exist."""

    avatar = None
    objects = IMQuerySet.as_manager()
    immutable_fields: ClassVar[tuple[str, ...]] = ()
    bloomerp_config = BloomerpModelConfig(
        module="communication",
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        string_search_settings=StringSearchSettings(allow_global_search=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )

    class Meta(BloomerpModel.Meta):
        abstract = True

    def check_conversation(self, field: str, actual: Any, expected: Any) -> None:
        """Reject a link that crosses conversation boundaries."""
        if actual != expected:
            raise ValidationError(
                {field: "The related record must belong to the same conversation."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate writes, freeze provenance and prevent read markers moving backward."""
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
                for field in self.immutable_fields:
                    if getattr(old, field) != getattr(self, field):
                        raise ValidationError(
                            {field: "This relation or identity is immutable."}
                        )
                if hasattr(self, "last_read_message_id") and old.last_read_message_id:
                    if (
                        not self.last_read_message_id
                        or self.last_read_message.sequence
                        < old.last_read_message.sequence
                    ):
                        raise ValidationError(
                            {
                                "last_read_message": "Read positions cannot move backward."
                            }
                        )
            super().save(*args, **kwargs)
