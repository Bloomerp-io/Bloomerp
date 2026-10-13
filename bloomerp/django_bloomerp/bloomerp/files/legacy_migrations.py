"""Keep historical migration upload paths importable without retired ORM models."""

from uuid import uuid4
from django.db.models import Model


def legacy_file_upload_to(instance: Model, filename: str) -> str:
    """Reproduce the initial File upload path for historical migration state only."""
    content_type = getattr(instance, "content_type", None)
    folder = content_type.app_label if content_type is not None else "others"
    return f"bloomerp/{folder}/{uuid4()}_{filename}"
