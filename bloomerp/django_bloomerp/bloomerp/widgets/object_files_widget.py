from typing import Any

from django import forms


class ObjectFilesWidget(forms.Widget):
    """Display manual file references as nodes and accept additional uploads."""

    template_name = "widgets/object_files_widget.html"

    def format_value(self, value: Any) -> list[Any]:
        """Resolve manual references and omit uploads that have no saved-file preview."""
        from bloomerp.models import FileReference

        if value is None:
            return []
        if hasattr(value, "all"):
            value = (
                value.filter(application_field__isnull=True, occurrence_id__isnull=True)
                .select_related("file")
                .order_by("-datetime_created")
            )
        elif not isinstance(value, (list, tuple)):
            return []
        current_files: list[Any] = []
        for item in value:
            if isinstance(item, FileReference):
                if item.application_field_id is not None:
                    continue
                item = item.file
            # Bound invalid forms contain UploadedFile values without node IDs.
            if getattr(item, "pk", None):
                current_files.append(item)
        return current_files

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Supply resolved file nodes and multiple-upload input attributes."""
        context = super().get_context(name, value, attrs)
        context["files"] = context["widget"]["value"]
        context["multiple"] = True
        return context

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        """Extract only uploaded bytes; existing usages are managed by reference controls."""
        return files.getlist(name)
