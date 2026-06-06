from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from django.core.files.base import File
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model, QuerySet
from django.db.models.fields.files import FieldFile


def make_json_safe(value: Any) -> Any:
    """Return a JSONField-safe representation of Python and Django values."""
    if isinstance(value, Model):
        return make_json_safe(value.pk)

    if isinstance(value, QuerySet):
        return [make_json_safe(obj) for obj in value]

    if isinstance(value, Mapping):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]

    if isinstance(value, FieldFile):
        return value.name or ""

    if isinstance(value, File):
        return value.name or ""

    try:
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder))
    except TypeError:
        return str(value)
