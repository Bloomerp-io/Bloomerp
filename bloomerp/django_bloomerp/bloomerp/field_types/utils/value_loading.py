from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from django.db.models import Model

from bloomerp.field_types.registry import BatchValueLoader

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


def prepare_field_values(
    objects: Iterable[Model], fields: Sequence[ApplicationField]
) -> Iterable[Model]:
    """Run each registered batch loader once for the fields displayed on a page."""
    batches: dict[BatchValueLoader, list[ApplicationField]] = {}
    for application_field in fields:
        loader = application_field.get_field_type().batch_value_loader
        if loader is not None:
            batches.setdefault(loader, []).append(application_field)
    if not batches:
        return objects
    prepared = list(objects)
    for loader, application_fields in batches.items():
        loader(prepared, application_fields)
    return prepared
