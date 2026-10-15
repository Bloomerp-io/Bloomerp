"""Validated private persistence for conferencing, independent of IM."""

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


class ConferenceQuerySet(models.QuerySet):
    """Require validated saves for conferencing identities and lifecycle records."""

    def update(self, **kwargs: Any) -> int:
        """Reject updates that bypass model validation and immutable fields."""
        raise TypeError("Conferencing records require instance.save().")

    def bulk_create(
        self, objs: Iterable[models.Model], *args: Any, **kwargs: Any
    ) -> list[models.Model]:
        """Reject inserts that bypass conferencing validation."""
        raise TypeError("Conferencing records require instance.save().")

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        *args: Any,
        **kwargs: Any,
    ) -> int:
        """Reject bulk updates that bypass conferencing validation."""
        raise TypeError("Conferencing records require instance.save().")


class ConferenceModel(BloomerpModel):
    """Keep conferencing records private and validate every ordinary save."""

    avatar = None
    objects = ConferenceQuerySet.as_manager()
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

    def validate_previous(self, previous: "ConferenceModel") -> None:
        """Prevent changes to the provenance and provider identities of a record."""
        for field in self.immutable_fields:
            if getattr(previous, field) != getattr(self, field):
                raise ValidationError(
                    {field: "This relation or identity is immutable."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Serialize validated updates to an existing conferencing record."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            if not self._state.adding:
                previous = (
                    type(self)
                    .objects.using(database)
                    .select_for_update()
                    .filter(pk=self.pk)
                    .first()
                )
                if previous is not None:
                    self.validate_previous(previous)
            self.full_clean()
            super().save(*args, **kwargs)
