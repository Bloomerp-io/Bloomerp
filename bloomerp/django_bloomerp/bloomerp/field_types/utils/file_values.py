from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.db.models import Model, Q
from django.utils.html import format_html_join
from django.utils.safestring import SafeString

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


def load_file_field_values(
    objects: Sequence[Model], fields: Sequence[ApplicationField]
) -> None:
    """Fetch all displayed attachment fields in one indexed reference query."""
    from bloomerp.models import FileFieldReference
    from bloomerp.permissions.manager import field_access_annotation_name

    if not objects or not fields:
        return
    parents = {(type(obj), str(obj.pk)): obj for obj in objects}
    definitions = {field.pk: (field.get_model(), field.field) for field in fields}
    scope = Q(pk__in=[])
    for field in fields:
        model, name = definitions[field.pk]
        permitted_ids = []
        for obj in objects:
            if type(obj) is not model:
                continue
            obj.__dict__.setdefault("_prefetched_objects_cache", {})[name] = []
            if getattr(obj, field_access_annotation_name(field), True):
                permitted_ids.append(str(obj.pk))
        if permitted_ids:
            scope |= Q(application_field_id=field.pk, object_id__in=permitted_ids)
    references = (
        FileFieldReference.objects.filter(scope).select_related("file").order_by("pk")
    )
    for reference in references:
        model, name = definitions[reference.application_field_id]
        parent = parents[(model, reference.object_id)]
        parent.__dict__["_prefetched_objects_cache"][name].append(reference.file)


def render_file_field_value(
    application_field: ApplicationField, instance: Model
) -> SafeString:
    """Render escaped file names and storage URLs from the prepared field value."""
    return format_html_join(
        ", ",
        '<a class="text-primary" href="{}">{}</a>',
        ((file.url, file.name) for file in getattr(instance, application_field.field)),
    )
