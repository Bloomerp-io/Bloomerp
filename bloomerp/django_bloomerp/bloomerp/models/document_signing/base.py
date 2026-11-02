"""Validated persistence shared by the provider-independent signing models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models, router, transaction

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    SearchSettings,
)
from bloomerp.modules.file_management import FileManagement

if TYPE_CHECKING:
    from .signature_request import SignatureRequest


def signing_builder_config(include_search_routes: bool = False) -> BloomerpModelConfig:
    """Enable protected SDK resources and opt builder routes out of search by default."""
    return BloomerpModelConfig(
        module=FileManagement,
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=True),
        string_search_settings=SearchSettings(
            allow_global_search=False, include_search_routes=include_search_routes
        ),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )


class SigningQuerySet(models.QuerySet):
    """Keep bulk writes from bypassing signing validation and evidence retention."""

    def update(self, **kwargs: Any) -> int:
        """Require validated instance saves for changes to signing records."""
        raise TypeError("Signing records require individual save() calls.")

    def bulk_create(
        self, objs: Iterable[models.Model], *args: Any, **kwargs: Any
    ) -> list[models.Model]:
        """Require validation when creating signing records."""
        raise TypeError("Signing records require individual save() calls.")

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        *args: Any,
        **kwargs: Any,
    ) -> int:
        """Require validation when changing several signing records."""
        raise TypeError("Signing records require individual save() calls.")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Apply instance retention rules to every requested deletion atomically."""
        count = 0
        labels: dict[str, int] = {}
        with transaction.atomic(using=self.db):
            for instance in self:
                deleted, details = instance.delete(using=self.db)
                count += deleted
                for label, amount in details.items():
                    labels[label] = labels.get(label, 0) + amount
        return count, labels


class SigningModel(BloomerpModel):
    """Validate signing records without exposing unfinished signing APIs or views."""

    avatar = None
    objects = SigningQuerySet.as_manager()
    immutable_fields: ClassVar[tuple[str, ...]] = ()
    append_only: ClassVar[bool] = False
    request_bound: ClassVar[bool] = False
    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        string_search_settings=SearchSettings(
            allow_global_search=False, include_search_routes=False
        ),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )

    class Meta(BloomerpModel.Meta):
        abstract = True

    def lock_request(self, database: str) -> None:
        """Serialize child writes with dispatch and completion of their request."""
        if self.request_bound and self.request_id:
            request_model = apps.get_model("bloomerp", "SignatureRequest")
            request_model.objects.using(database).select_for_update().filter(
                pk=self.request_id
            ).first()

    def get_request(self) -> SignatureRequest | None:
        """Read current request state instead of trusting a cached related instance."""
        request_model = apps.get_model("bloomerp", "SignatureRequest")
        return (
            request_model.objects.using(self._state.db)
            .filter(pk=self.request_id)
            .first()
        )

    def require_unchanged(self, previous: SigningModel, fields: Iterable[str]) -> None:
        """Reject changes to the specified stored identities or snapshot values."""
        errors = {
            field: "This signing identity or snapshot is immutable."
            for field in fields
            if getattr(previous, field) != getattr(self, field)
        }
        if errors:
            raise ValidationError(errors)

    def validate_previous(self, previous: SigningModel) -> None:
        """Retain append-only evidence and immutable parent identities."""
        if self.append_only:
            raise ValidationError("Signing evidence is append-only.")
        self.require_unchanged(previous, self.immutable_fields)

    def validate_deletion(self) -> None:
        """Retain evidence and permit removal of request children only in drafts."""
        if self.append_only:
            raise ValidationError("Signing evidence is append-only.")
        if self.request_bound:
            request = self.get_request()
            if request is not None and request.status != "draft":
                raise ValidationError("Only draft signing records can be deleted.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate an entire record while locking its aggregate and stored version."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self._state.db = database
        with transaction.atomic(using=database):
            self.lock_request(database)
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
            if previous is not None and kwargs.get("update_fields") is not None:
                update_fields = frozenset(kwargs["update_fields"])
                kwargs["update_fields"] = update_fields
                fields = self._meta.concrete_fields
                persisted = type(self).from_db(
                    database,
                    [field.attname for field in fields],
                    [
                        getattr(
                            self
                            if field.name in update_fields
                            or field.attname in update_fields
                            else previous,
                            field.attname,
                        )
                        for field in fields
                    ],
                )
                persisted.validate_previous(previous)
                persisted.full_clean()
            super().save(*args, **kwargs)

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Check retention under the same request lock used by ordinary writes."""
        database = using or router.db_for_write(type(self), instance=self)
        self._state.db = database
        with transaction.atomic(using=database):
            self.lock_request(database)
            stored = (
                type(self).objects.using(database).select_for_update().get(pk=self.pk)
            )
            stored.validate_deletion()
            return super().delete(using=database, keep_parents=keep_parents)
