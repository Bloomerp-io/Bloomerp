from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Model
from django.utils.translation import gettext_lazy as _

from bloomerp.form_fields.structured_value import StructuredFormValue
from bloomerp.widgets.file_field_widget import BloomerpFileFieldWidget


@dataclass
class FileFieldCleanedData(StructuredFormValue):
    """Validated uploads and retained IDs with deferred field-owned persistence."""

    model_field: Any
    retained: list[str] = field(default_factory=list)
    uploads: list[UploadedFile] = field(default_factory=list)
    _saved: bool = field(default=False, init=False)

    def save(self, parent: Model, *, user: Any = None) -> None:
        """Persist attachments exactly once through their owning model field."""
        if not self._saved:
            self.model_field.on_save(parent, self.retained, self.uploads)
            self.retained = [
                str(file.pk) for file in getattr(parent, self.model_field.name)
            ]
            self.uploads = []
            self._saved = True

    def serialize(self) -> list[str]:
        """Expose saved IDs; pending upload bytes cannot be serialized as IDs."""
        if self.uploads and not self._saved:
            raise ValueError("Save attachments before serializing their IDs.")
        return list(self.retained)


class BloomerpFileFormField(forms.Field):
    """Validate uploads and prevent retained IDs from crossing object/field boundaries."""

    def __init__(
        self,
        *,
        model_field: Any = None,
        multiple: bool = False,
        allowed_extensions: list[str] | str = "__all__",
        max_files: int | None = None,
        max_file_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure upload validation and a plain single/multiple file input."""
        self.model_field = model_field
        self.multiple = multiple
        self.allowed_extensions = allowed_extensions
        self.max_files = max_files
        self.max_file_size = max_file_size
        self.parent: Model | None = None
        kwargs.setdefault("widget", BloomerpFileFieldWidget(multiple=multiple))
        super().__init__(**kwargs)

    def bind_parent(self, parent: Model) -> None:
        """Bind validation and rendering to the current parent and owning field."""
        self.parent = parent
        self.widget.bind_parent(parent, self.model_field)

    def prepare_value(self, value: Any) -> Any:
        """Render retained files when redisplaying a bound structured value."""
        if isinstance(value, FileFieldCleanedData):
            return value.retained
        if isinstance(value, (list, tuple)):
            return [str(getattr(item, "pk", item)) for item in value]
        return value

    def bound_data(self, data: Any, initial: Any) -> Any:
        """Keep existing attachments visible when uploads fail validation."""
        if self.disabled:
            return initial
        return data if data is not None else initial

    def clean(self, value: Any) -> FileFieldCleanedData:
        """Validate every upload and retained ID without writing to storage or the DB."""
        from uuid import UUID

        from django.contrib.contenttypes.models import ContentType

        from bloomerp.models.files.file import File

        if isinstance(value, FileFieldCleanedData):
            return value
        if isinstance(value, dict):
            raw_ids = value.get("retained", [])
            uploads = value.get("uploads", [])
        else:
            values = value if isinstance(value, (list, tuple)) else [value]
            raw_ids = [
                item.pk if isinstance(item, File) else item
                for item in values
                if item and not isinstance(item, UploadedFile)
            ]
            uploads = [item for item in values if isinstance(item, UploadedFile)]
        try:
            retained = list(dict.fromkeys(str(UUID(str(pk))) for pk in raw_ids))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError(_("Invalid attachment ID.")) from error
        if any(not isinstance(upload, UploadedFile) for upload in uploads):
            raise ValidationError(_("Invalid uploaded file."))
        count = len(retained) + len(uploads)
        if self.required and not count:
            raise ValidationError(self.error_messages["required"], code="required")
        if (not self.multiple and count > 1) or (
            self.max_files is not None and count > self.max_files
        ):
            raise ValidationError(_("Too many files."))
        for upload in uploads:
            if self.allowed_extensions != "__all__":
                allowed = {
                    f".{extension.lstrip('.').lower()}"
                    for extension in self.allowed_extensions
                }
                if Path(upload.name).suffix.lower() not in allowed:
                    raise ValidationError(_("Unsupported file extension."))
            if self.max_file_size is not None and upload.size > self.max_file_size:
                raise ValidationError(_("File exceeds the maximum size."))
        if retained:
            if (
                self.parent is None
                or self.parent._state.adding
                or self.model_field is None
            ):
                raise ValidationError(
                    _("Attachments do not belong to this object and field.")
                )
            owned = File.objects.filter(
                pk__in=retained,
                field_reference__application_field__content_type=ContentType.objects.get_for_model(
                    self.parent
                ),
                field_reference__object_id=str(self.parent.pk),
                field_reference__application_field__field=self.model_field.name,
            )
            if owned.count() != len(retained):
                raise ValidationError(
                    _("Attachments do not belong to this object and field.")
                )
        result = FileFieldCleanedData(self.model_field, retained, list(uploads))
        self.run_validators(result)
        return result

    def has_changed(self, initial: Any, data: Any) -> bool:
        """Detect added uploads or a changed retained-ID list, respecting disabled fields."""
        if self.disabled:
            return False
        if isinstance(data, dict):
            return bool(data.get("uploads")) or [
                str(getattr(pk, "pk", pk)) for pk in (initial or [])
            ] != data.get("retained", [])
        return super().has_changed(initial, data)
