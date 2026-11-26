from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.utils.translation import gettext as _

from bloomerp.form_fields.structured_value import (
    StructuredFormValue,
    serialize_form_value,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager, field_access_annotation_name

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


ROW_ID_KEY = "id"
ROW_DELETE_KEY = "DELETE"
ROW_INSERT_KEY = "INSERT"


@dataclass
class OneToManyCleanedData(StructuredFormValue):
    """Validated one-to-many changes produced without writing to the database."""

    application_field: ApplicationField
    to_save: list[models.Model] = dataclass_field(default_factory=list)
    to_delete: list[models.Model] = dataclass_field(default_factory=list)
    to_insert: list[models.Model] = dataclass_field(default_factory=list)
    insertion_user: AbstractBaseUser | None = dataclass_field(default=None, repr=False)
    _forms: list[forms.ModelForm] = dataclass_field(default_factory=list, repr=False)
    _saved: bool = dataclass_field(default=False, init=False, repr=False)

    def save(self, parent: models.Model, *, user: AbstractBaseUser | None = None) -> None:
        """Persist the validated changes after the parent object has been saved."""
        if self._saved:
            return
        if self.to_insert:
            self._save_insertions(parent)
        for instance in self.to_delete:
            instance.delete()

        for child_form, instance in zip(self._forms, self.to_save):
            parent_field_name = self.application_field._get_model_field().field.name
            setattr(instance, parent_field_name, parent)
            instance.save()
            child_form.save_m2m()
        self._saved = True

    def _save_insertions(self, parent: models.Model) -> None:
        """Link authorized rows while rejecting records claimed since validation."""
        relation = OneToManyField.get_insert_relation(self.application_field)
        queryset = OneToManyField.get_insertable_queryset(self.application_field, self.insertion_user)
        manager = UserPolicyManager(self.insertion_user)
        if relation is None or queryset is None:
            raise ValidationError(_("Existing records cannot be inserted here."))
        with transaction.atomic():
            available = queryset.filter(pk__in=[child.pk for child in self.to_insert])
            children = list(
                queryset.model._base_manager.filter(
                    pk__in=available.values("pk"), **{f"{relation.name}__isnull": True},
                ).order_by("pk").select_for_update()
            )
            if len(children) != len(self.to_insert):
                raise ValidationError(_("A selected record is no longer available."))
            for child in children:
                setattr(child, relation.name, parent)
                relation.clean(getattr(child, relation.attname), child)
                if not manager.candidate_matches_row_policies(child, BloomerpPermission.CHANGE):
                    raise ValidationError(_("You cannot link a selected record to this object."))
                child.save(update_fields=[relation.name])

    def serialize(self) -> list[dict[str, Any]]:
        """Serialize pending inserts alongside edited, created, and deleted rows."""
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
        rows.extend({ROW_ID_KEY: str(instance.pk), ROW_INSERT_KEY: True} for instance in self.to_insert)
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
        self.insertion_user: AbstractBaseUser | None = None

    def bind_parent(self, instance: models.Model | None) -> None:
        """Bind ordinary inline edits to the owning record."""
        self.parent_instance = instance

    def enable_existing_insertion(self, user: AbstractBaseUser) -> None:
        """Enable insertion for an authenticated model CRUD form and its widget."""
        if user.is_authenticated:
            self.insertion_user = user
            self.widget.insertion_user = user

    @staticmethod
    def get_insert_relation(application_field: ApplicationField) -> models.ForeignKey | None:
        """Resolve the editable nullable foreign key behind an inline relation."""
        try:
            reverse_relation = application_field._get_model_field()
        except (AttributeError, FieldDoesNotExist):
            return None
        relation = getattr(reverse_relation, "field", None)
        if (
            isinstance(reverse_relation, models.ManyToOneRel)
            and isinstance(relation, models.ForeignKey)
            and relation.null
            and relation.editable
        ):
            return relation
        return None

    @classmethod
    def get_insertable_queryset(
        cls, application_field: ApplicationField, user: AbstractBaseUser | None,
    ) -> models.QuerySet | None:
        """Scope insertion to unassigned rows the viewer can read and relink."""
        from bloomerp.models.application_field import ApplicationField

        relation = cls.get_insert_relation(application_field)
        if relation is None or user is None or not user.is_authenticated:
            return None
        child_model = relation.model
        link_field = ApplicationField.get_by_field(child_model, relation.name)
        if link_field is None:
            return None
        manager = UserPolicyManager(user)
        visible = manager.get_queryset(child_model, BloomerpPermission.VIEW)
        changeable = manager.get_queryset(child_model, BloomerpPermission.CHANGE).filter(
            pk__in=visible.values("pk"),
            **{f"{relation.name}__isnull": True},
        )
        return manager.annotate_field_permissions(
            changeable, [link_field], BloomerpPermission.CHANGE,
        ).filter(**{field_access_annotation_name(link_field): True})

    def clean(self, value: Any) -> OneToManyCleanedData:
        """Validate inline rows with repeated selections and separate child-form uploads."""
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
        result = OneToManyCleanedData(
            application_field=self.application_field, insertion_user=self.insertion_user,
        )
        inserted_ids: set[object] = set()
        errors: list[ValidationError] = []

        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                errors.append(ValidationError(f"Row {row_number}: invalid row data."))
                continue
            if self._is_blank_row(row):
                continue

            if self._is_truthy(row.get(ROW_INSERT_KEY)):
                try:
                    instance = self._get_insertable_instance(row)
                    if instance.pk in inserted_ids:
                        raise ValidationError(_("This record is already in the form."))
                except ValidationError as exc:
                    errors.append(ValidationError(f"Row {row_number}: {exc.message}"))
                    continue
                inserted_ids.add(instance.pk)
                result.to_insert.append(instance)
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
                self._row_form_data(row, child_form_class.base_fields),
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

    def _get_insertable_instance(self, row: dict[str, Any]) -> models.Model:
        """Reject forged or stale insertions without applying any submitted child values."""
        queryset = self.get_insertable_queryset(self.application_field, self.insertion_user)
        if queryset is None or self._is_truthy(row.get(ROW_DELETE_KEY)):
            raise ValidationError(_("Existing records cannot be inserted here."))
        try:
            return queryset.get(pk=row.get(ROW_ID_KEY))
        except (queryset.model.DoesNotExist, ValidationError, ValueError, TypeError):
            raise ValidationError(_("A selected record is no longer available."))

    @staticmethod
    def _row_form_data(
        row: dict[str, Any], form_fields: Mapping[str, forms.Field]
    ) -> dict[str, Any]:
        """Normalize only multiple-choice values, preserving scalar, JSON, and file data."""
        data = row.copy()
        for name, field in form_fields.items():
            if name not in data or not isinstance(
                field, (forms.MultipleChoiceField, forms.ModelMultipleChoiceField)
            ):
                continue
            value = data[name]
            if value in (None, ""):
                data[name] = []
            elif not isinstance(value, (list, tuple)):
                data[name] = [value]
        return data

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
