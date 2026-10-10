"""Expose shared object labels as a read-only virtual model field."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import models


class LabelsDescriptor:
    """Resolve label values from the existing generic assignment table."""

    def __init__(self, field: BloomerpLabelsField) -> None:
        """Remember the field returned when accessed on the model class."""
        self.field = field

    def __get__(self, instance: models.Model | None, owner: type[models.Model]) -> Any:
        """Return assigned labels, or an empty collection for unsaved objects."""
        from bloomerp.models.communication.label import Label

        if instance is None:
            return self.field
        if instance._state.adding:
            return []
        return list(
            Label.objects.using(instance._state.db or "default")
            .filter(
                objectlabel__content_type=ContentType.objects.db_manager(
                    instance._state.db or "default"
                ).get_for_model(instance),
                objectlabel__object_id=str(instance.pk),
            )
            .order_by("name", "pk")
        )

    def __set__(self, instance: models.Model, value: Any) -> None:
        """Keep assignment changes in the existing label-reference workflow."""
        if value == self.__get__(instance, type(instance)):
            return
        raise TypeError("Use the label-reference workflow to update labels.")


class BloomerpLabelsField(models.Field):
    """Discover and filter labels without storing a column on every parent model."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Make the computed label collection read-only in generated model forms."""
        kwargs.update(editable=False, blank=True)
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs: Any) -> forms.Field:
        """Display labels without accepting writes through generated model forms."""
        return forms.Field(
            label=self.verbose_name, required=False, disabled=True, **kwargs
        )

    def get_attname_column(self) -> tuple[str, None]:
        """Keep the field out of the parent table's physical columns."""
        return self.get_attname(), None

    def db_type(self, connection: Any) -> None:
        """Delegate persistence to ObjectLabel rather than a parent column."""
        return

    def contribute_to_class(
        self, cls: type[models.Model], name: str, **kwargs: Any
    ) -> None:
        """Register inherited private metadata and the label-value descriptor."""
        kwargs["private_only"] = True
        super().contribute_to_class(cls, name, **kwargs)
        setattr(cls, name, LabelsDescriptor(self))
