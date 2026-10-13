from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.db.models.signals import post_delete

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


class FileFieldDescriptor:
    """Expose reference-backed attachments without a column on the parent model."""

    def __init__(self, field: BloomerpFileField) -> None:
        """Remember the virtual field whose attachments this descriptor loads."""
        self.field = field

    def __get__(self, instance: models.Model | None, owner: type[models.Model]) -> Any:
        """Return the field on the class and its attachment records on an instance."""
        if instance is None:
            return self.field
        if instance._state.adding:
            return []
        cache = instance.__dict__.setdefault("_prefetched_objects_cache", {})
        if self.field.name not in cache:
            from bloomerp.field_types.utils.file_values import load_file_field_values

            application_field = self.field.get_application_field(instance)
            load_file_field_values([instance], [application_field])
        return cache[self.field.name]

    def __set__(self, instance: models.Model, value: Any) -> None:
        """Accept unchanged Django cleaning values while rejecting direct attachment edits."""
        current = self.__get__(instance, type(instance))
        if self.field.to_python(current) == self.field.to_python(value):
            return
        raise TypeError("Use the file form or field.on_save() to update attachments.")


class BloomerpFileField(models.Field):
    """Declare file cardinality and validation over the shared reference table."""

    def __init__(
        self,
        *args: Any,
        multiple: bool = False,
        allowed_extensions: list[str] | str | None = None,
        max_files: int | None = None,
        max_file_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure cardinality, accepted extensions, and upload size in bytes."""
        self.multiple = multiple
        self.allowed_extensions = (
            "__all__" if allowed_extensions in (None, []) else allowed_extensions
        )
        if (
            isinstance(self.allowed_extensions, str)
            and self.allowed_extensions != "__all__"
        ):
            raise ValueError("allowed_extensions must be a list or __all__")
        self.max_files = max_files
        self.max_file_size = max_file_size
        if max_files is not None and max_files < 1:
            raise ValueError("max_files must be positive")
        if max_file_size is not None and max_file_size < 1:
            raise ValueError("max_file_size must be positive")
        kwargs.setdefault("default", list)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        """Preserve attachment options when Django serializes migrations."""
        name, path, args, kwargs = super().deconstruct()
        kwargs.update(
            multiple=self.multiple, allowed_extensions=self.allowed_extensions
        )
        if self.max_files is not None:
            kwargs["max_files"] = self.max_files
        if self.max_file_size is not None:
            kwargs["max_file_size"] = self.max_file_size
        return name, path, args, kwargs

    def get_attname_column(self) -> tuple[str, None]:
        """Keep this field virtual instead of allocating a database column."""
        return self.get_attname(), None

    def db_type(self, connection: Any) -> None:
        """The reference table owns storage, so the parent needs no SQL type."""
        return

    def to_python(self, value: Any) -> list[str]:
        """Normalize submitted attachment identifiers for validation and serialization."""
        if value in (None, "", False):
            return []
        values = value if isinstance(value, (list, tuple)) else [value]
        try:
            return list(
                dict.fromkeys(
                    str(UUID(str(getattr(item, "pk", item)))) for item in values
                )
            )
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError("Invalid attachment ID.") from error

    def get_prep_value(self, value: Any) -> list[str]:
        """Normalize IDs for callers; this virtual field never writes a parent column."""
        return self.to_python(value)

    def formfield(self, **kwargs: Any) -> forms.Field:
        """Build an upload editor that defers attachment mutations until save."""
        from bloomerp.form_fields.bloomerp_file_field import BloomerpFileFormField

        defaults = {
            "form_class": BloomerpFileFormField,
            "model_field": self,
            "multiple": self.multiple,
            "allowed_extensions": self.allowed_extensions,
            "max_files": self.max_files,
            "max_file_size": self.max_file_size,
        }
        defaults.update(kwargs)
        return models.Field.formfield(self, **defaults)

    def save_form_data(self, instance: models.Model, data: Any) -> None:
        """Leave attachment writes to the validated structured-form lifecycle."""
        return

    def validate(self, value: Any, model_instance: models.Model) -> None:
        """Validate attachment cardinality during model cleaning."""
        ids = self.to_python(value)
        if (not self.multiple and len(ids) > 1) or (
            self.max_files is not None and len(ids) > self.max_files
        ):
            raise ValidationError("Too many files.")
        super().validate(ids, model_instance)

    def contribute_to_class(
        self, cls: type[models.Model], name: str, **kwargs: Any
    ) -> None:
        """Register a private virtual field and clean references when its parent dies."""
        kwargs["private_only"] = True
        super().contribute_to_class(cls, name, **kwargs)
        setattr(cls, name, FileFieldDescriptor(self))
        post_delete.connect(
            self._delete_parent_references,
            sender=cls,
            weak=False,
            dispatch_uid=f"bloomerp.file_field.{cls._meta.label_lower}.{name}",
        )

    def get_application_field(self, parent: models.Model) -> ApplicationField:
        """Resolve the registered application field identifying this attachment slot."""
        from django.contrib.contenttypes.models import ContentType

        from bloomerp.models import ApplicationField

        return ApplicationField.objects.get(
            content_type=ContentType.objects.get_for_model(parent),
            field=self.name,
        )

    def _delete_parent_references(
        self,
        sender: type[models.Model],
        instance: models.Model,
        using: str = "default",
        **kwargs: Any,
    ) -> None:
        """Remove this field's usages while retaining reusable file nodes and bytes."""
        from django.contrib.contenttypes.models import ContentType

        from bloomerp.models import FileReference

        FileReference.objects.using(using).filter(
            content_type=ContentType.objects.db_manager(using).get_for_model(sender),
            application_field__field=self.name,
            object_id=str(instance.pk),
        ).delete()

    def on_save(
        self,
        parent: models.Model,
        retained: list[str],
        uploads: list[UploadedFile],
        *,
        user: Any = None,
    ) -> None:
        """Synchronize references and uploaded files after the validated parent saves."""
        from bloomerp.models.files.file_node import FileNode
        from bloomerp.models.files.file_reference import FileReference

        if parent._state.adding:
            raise ValueError("Save the parent before its attachments.")
        form_field = self.formfield()
        form_field.bind_parent(parent)
        validated = form_field.clean({"retained": retained, "uploads": uploads})
        application_field = self.get_application_field(parent)
        actor = user or getattr(parent, "updated_by", None)
        created: list[FileNode] = []
        try:
            with transaction.atomic():
                # Serialize edits on the parent even when it has no references yet.
                parent.__class__._base_manager.select_for_update().get(pk=parent.pk)
                owned = FileReference.objects.filter(
                    content_type_id=application_field.content_type_id,
                    application_field=application_field,
                    object_id=str(parent.pk),
                    occurrence_id__isnull=True,
                )
                existing_ids = {
                    str(pk) for pk in owned.values_list("file_id", flat=True)
                }
                if set(validated.retained) - existing_ids:
                    raise ValidationError(
                        "Attachments do not belong to this object and field."
                    )
                for upload in validated.uploads:
                    file = FileNode(
                        content=upload,
                        name=upload.name,
                        kind="FILE",
                        created_by=actor,
                        updated_by=actor,
                    )
                    created.append(file)
                    file.save()
                    FileReference.objects.create(
                        file=file,
                        content_object=parent,
                        application_field=application_field,
                    )
                owned.filter(file_id__in=existing_ids).exclude(
                    file_id__in=validated.retained
                ).delete()
        except Exception:
            for file in created:
                if file.content and file.content._committed:
                    file.content.delete(save=False)
            raise
        parent.__dict__.pop("_prefetched_objects_cache", None)
