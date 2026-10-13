from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Model

from bloomerp.form_fields.structured_value import StructuredFormValue


@dataclass
class FilesCleanedData(StructuredFormValue):
    """Defer generic attachment uploads until their parent has been saved."""

    files: list[UploadedFile] = field(default_factory=list)
    saved_file_ids: list[str] = field(default_factory=list, init=False)
    _saved: bool = field(default=False, init=False, repr=False)

    def save(self, parent: Model, *, user: Any = None) -> None:
        """Create one node and record-level reference per upload, once per submission."""
        from bloomerp.models import FileNode, FileReference

        if self._saved or not self.files:
            return
        if parent._state.adding:
            raise ValueError("Save the parent before its attachments.")
        actor = user or getattr(parent, "updated_by", None)
        created: list[FileNode] = []
        try:
            with transaction.atomic():
                for upload in self.files:
                    node = FileNode(
                        content=upload,
                        name=upload.name,
                        kind="FILE",
                        created_by=actor,
                        updated_by=actor,
                    )
                    created.append(node)
                    node.save()
                    FileReference.objects.create(
                        file=node,
                        content_object=parent,
                        created_by=actor,
                        updated_by=actor,
                    )
        except Exception:
            for node in created:
                if node.content and node.content._committed:
                    node.content.delete(save=False)
            raise
        parent.__dict__.pop("_prefetched_objects_cache", None)
        self.saved_file_ids = [str(node.pk) for node in created]
        self._saved = True

    def serialize(self) -> list[str]:
        """Preserve upload names in serialized public-form submission data."""
        return [uploaded_file.name for uploaded_file in self.files]


class FilesRelationField(forms.Field):
    """Return uploaded object files as a structured, persistable value."""

    def bound_data(self, data: Any, initial: Any) -> Any:
        """Preserve attachment display when a submission contains no new uploads."""
        if data in (None, "", [], ()):
            return initial
        return data

    def clean(self, value: Any) -> FilesCleanedData:
        """Collect new uploads without treating existing reference records as uploads."""
        value = super().clean(value) or []
        if not isinstance(value, (list, tuple)):
            value = [value]
        return FilesCleanedData(
            files=[item for item in value if isinstance(item, UploadedFile)],
        )
