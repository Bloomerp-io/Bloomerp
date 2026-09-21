from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models

from bloomerp.form_fields.structured_value import (
    StructuredFormValue,
    serialize_form_value,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


ROW_ID_KEY = "id"
ROW_DELETE_KEY = "DELETE"


@dataclass
class OneToManyCleanedData(StructuredFormValue):
    """Validated one-to-many changes produced without writing to the database."""

    application_field: ApplicationField
    to_save: list[models.Model] = dataclass_field(default_factory=list)
    to_delete: list[models.Model] = dataclass_field(default_factory=list)
    _forms: list[forms.ModelForm] = dataclass_field(default_factory=list, repr=False)
    _saved: bool = dataclass_field(default=False, init=False, repr=False)

    def save(self, parent: models.Model, *, user=None) -> None:
        """Persist the validated changes after the parent object has been saved."""
        if self._saved:
            return
        for instance in self.to_delete:
            instance.delete()

        for child_form, instance in zip(self._forms, self.to_save):
            parent_field_name = self.application_field._get_model_field().field.name
            setattr(instance, parent_field_name, parent)
            instance.save()
            child_form.save_m2m()
        self._saved = True

    def serialize(self) -> list[dict[str, Any]]:
        rows = []
        for child_form, instance in zip(self._forms, self.to_save):
            row = {
                key: serialize_form_value(value)
                for key, value in child_form.cleaned_data.items()
            }
            row[ROW_ID_KEY] = (
                str(instance.pk)
                if instance.pk and not instance._state.adding
                else ""
            )
            rows.append(row)
        rows.extend(
            {
                ROW_ID_KEY: str(instance.pk),
                ROW_DELETE_KEY: True,
            }
            for instance in self.to_delete
        )
        return rows

class OneToManyField(forms.Field):
    """Validate inline child rows and return related instances grouped by action."""

    def __init__(
        self,
        *,
        application_field: ApplicationField,
        **kwargs: Any,
    ) -> None:
        """Initialize an inline field for one reverse model relation."""
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.application_field = application_field
        self.related_model = application_field.get_related_model()
        self.parent_model = application_field.get_model()
        self.parent_instance: models.Model | None = None
        self.parent_field_name = self._resolve_parent_field_name()

    def bind_parent(self, instance: models.Model | None) -> None:
        self.parent_instance = instance

    def clean(self, value: Any) -> OneToManyCleanedData:
        """Validate inline rows with nested uploads bound as child-form files."""
        rows = super().clean(value) or []
        if not isinstance(rows, list):
            raise ValidationError("Invalid one-to-many field value.", code="invalid")
        if self.related_model is None or self.parent_field_name is None:
            raise ValidationError("Unable to resolve the related model.", code="invalid_relation")

        child_fields = [column.field for column in self.widget.get_columns()]
        child_form_class = forms.modelform_factory(
            self.related_model,
            fields=child_fields,
        )
        result = OneToManyCleanedData(application_field=self.application_field)
        errors: list[ValidationError] = []

        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                errors.append(ValidationError(f"Row {row_number}: invalid row data."))
                continue
            if self._is_blank_row(row):
                continue

            try:
                instance = self._get_existing_instance(row.get(ROW_ID_KEY))
            except ValidationError as exc:
                errors.append(ValidationError(f"Row {row_number}: {exc.message}"))
                continue

            if self._is_truthy(row.get(ROW_DELETE_KEY)):
                if instance is not None:
                    result.to_delete.append(instance)
                continue

            child_form = child_form_class(
                row,
                files=self._uploaded_files(row),
                instance=instance,
            )
            if not child_form.is_valid():
                errors.append(
                    ValidationError(
                        f"Row {row_number}: {child_form.errors.as_text()}",
                        code="invalid_child",
                    )
                )
                continue

            child = child_form.save(commit=False)
            if self.parent_instance is not None:
                setattr(child, self.parent_field_name, self.parent_instance)
            result.to_save.append(child)
            result._forms.append(child_form)

        if errors:
            raise ValidationError(errors)
        return result

    @staticmethod
    def _uploaded_files(row: dict[str, Any]) -> dict[str, UploadedFile]:
        """Return only genuine uploads for the child form's file mapping."""
        return {
            field_name: value
            for field_name, value in row.items()
            if isinstance(value, UploadedFile)
        }

    def _resolve_parent_field_name(self) -> str | None:
        try:
            relation = self.parent_model._meta.get_field(self.application_field.field)
        except (AttributeError, LookupError):
            return None
        relation_field = getattr(relation, "field", None)
        return getattr(relation_field, "name", None)

    def _get_existing_instance(self, object_id: Any) -> models.Model | None:
        if object_id in (None, ""):
            return None
        if self.parent_instance is None or self.parent_instance.pk is None:
            raise ValidationError("Existing related objects cannot be used before the parent is saved.")

        queryset = self.related_model._default_manager.filter(
            **{self.parent_field_name: self.parent_instance}
        )
        try:
            return queryset.get(pk=object_id)
        except (self.related_model.DoesNotExist, ValueError, TypeError):
            raise ValidationError("Invalid related object.", code="invalid_related_object")

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @classmethod
    def _is_blank_row(cls, row: dict[str, Any]) -> bool:
        if cls._is_truthy(row.get(ROW_DELETE_KEY)):
            return False
        return not any(
            value not in (None, "", [])
            for field_name, value in row.items()
            if field_name not in {ROW_ID_KEY, ROW_DELETE_KEY}
        ) and row.get(ROW_ID_KEY) in (None, "")
