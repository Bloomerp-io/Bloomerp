from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Model
from django.forms.widgets import FileInput


class BloomerpFileFieldWidget(FileInput):
    """Extract uploads and retained IDs without mutating files during rendering."""

    template_name = "widgets/bloomerp_file_field_widget.html"

    def __init__(
        self, attrs: dict[str, Any] | None = None, *, multiple: bool = False
    ) -> None:
        """Configure a normal HTML file input for single or multiple uploads."""
        self.allow_multiple_selected = multiple
        self.parent: Model | None = None
        self.model_field: Any = None
        super().__init__(attrs)

    def bind_parent(self, parent: Model, model_field: Any) -> None:
        """Scope existing-file display to the owning parent and model field."""
        self.parent = parent
        self.model_field = model_field

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Render only current field-owned files and the plain upload input."""
        from django.contrib.contenttypes.models import ContentType

        from bloomerp.models.files.file_node import FileNode

        context = super().get_context(name, None, attrs)
        context["current_files"] = []
        if (
            self.parent is not None
            and not self.parent._state.adding
            and self.model_field is not None
        ):
            ids = value.get("retained", []) if isinstance(value, dict) else value
            if ids:
                ids = ids if isinstance(ids, (list, tuple)) else [ids]
                try:
                    ids = [str(UUID(str(getattr(pk, "pk", pk)))) for pk in ids]
                except (ValueError, TypeError, AttributeError):
                    ids = []
                context["current_files"] = FileNode.objects.filter(
                    pk__in=ids,
                    references__occurrence_id__isnull=True,
                    references__content_type=ContentType.objects.get_for_model(
                        self.parent
                    ),
                    references__object_id=str(self.parent.pk),
                    references__application_field__field=self.model_field.name,
                )
        return context

    def value_from_datadict(self, data: Any, files: Any, name: str) -> dict[str, Any]:
        """Return uploads and checked retention controls without saving any files."""
        uploads = (
            files.getlist(name) if hasattr(files, "getlist") else files.get(name, [])
        )
        if not isinstance(uploads, (list, tuple)):
            uploads = [uploads] if uploads else []
        retained = (
            data.getlist(f"{name}__retain")
            if hasattr(data, "getlist")
            else data.get(f"{name}__retain", [])
        )
        if not isinstance(retained, (list, tuple)):
            retained = [retained] if retained else []
        # Partial model forms fill omitted fields using their ordinary field key.
        if (
            f"{name}__present" not in data
            and f"{name}__retain" not in data
            and not uploads
        ):
            retained = (
                data.getlist(name) if hasattr(data, "getlist") else data.get(name, [])
            )
            if not isinstance(retained, (list, tuple)):
                retained = [retained] if retained else []
        # Uploading a replacement to a single-file editor drops its old file.
        if uploads and not self.allow_multiple_selected:
            retained = []
        return {"uploads": list(uploads), "retained": list(retained)}

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Recognize an explicit empty editor independently from omitted PATCH data."""
        return (
            name not in files
            and name not in data
            and f"{name}__present" not in data
            and f"{name}__retain" not in data
        )

    def use_required_attribute(self, initial: Any) -> bool:
        """Validate combined retained/new files on the server rather than the upload input."""
        return False
