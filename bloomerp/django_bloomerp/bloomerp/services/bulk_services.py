from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, TextIOWrapper
from typing import Any

import pandas as pd
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet
from django.forms import BaseFormSet, formset_factory
from django.forms.widgets import CheckboxInput, CheckboxSelectMultiple, HiddenInput, RadioSelect
from django.http import QueryDict

from bloomerp.forms.bulk_upload_form import (
    AUTO_MANAGED_FIELD_NAMES,
    BloomerpDownloadBulkUploadTemplateForm,
)
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.models.files import File
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.tasks.base import is_celery_available
from bloomerp.utils.model_io import BloomerpModelIO


DEFAULT_REVIEW_PAGE_SIZE = 50
MAX_VALIDATION_ERRORS = 25


@dataclass
class BulkUploadDraft:
    file_id: str
    selected_fields: list[str]
    total_rows: int
    original_filename: str


@dataclass
class BulkUploadReviewPage:
    formset: BaseFormSet
    fields: list[str]
    page: int
    page_size: int
    total_rows: int
    total_pages: int
    start_row: int
    end_row: int
    page_row_errors: dict[int, dict[str, list[str]]]
    invalid_row_indexes: list[str]
    ordered_row_indexes: list[int]


@dataclass
class BulkUploadValidationSummary:
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: list[dict[str, Any]]

    @property
    def is_valid(self) -> bool:
        return self.invalid_rows == 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BulkCrudService:
    def __init__(self, model: type[Model], user):
        self.model = model
        self.user = user
        self.content_type = ContentType.objects.get_for_model(model)
        self.permission_manager = UserPermissionManager(user)
        self.model_io = BloomerpModelIO(model)
        self.bulk_add_permission = create_permission_str(model, "bulk_add")
        self.add_permission = create_permission_str(model, "add")

    @classmethod
    def from_content_type_id(cls, content_type_id: int, user) -> "BulkCrudService":
        """Create a bulk upload service for the model behind a content type.

        Args:
            content_type_id (int): Primary key of the Django content type to resolve.
            user: User performing the bulk upload flow.

        Returns:
            BulkCrudService: Service configured for the resolved model and user.
        """
        content_type = ContentType.objects.get(id=content_type_id)
        model = content_type.model_class()
        if model is None:
            raise ValidationError("Invalid content type.")
        return cls(model=model, user=user)

    def can_access_page(self) -> bool:
        """
        Whether the user has permission to access the bulk upload page for this service's model.
        """
        return self.permission_manager.has_global_permission(self.model, self.bulk_add_permission)

    def get_allowed_application_fields(self) -> QuerySet[ApplicationField]:
        """
        Get the application fields that the user is allowed to access for this service's model.
        """
        bulk_fields = self.permission_manager.get_accessible_fields(self.content_type, self.bulk_add_permission)
        add_fields = self.permission_manager.get_accessible_fields(self.content_type, self.add_permission)
        allowed_ids = set(bulk_fields.values_list("id", flat=True)) | set(add_fields.values_list("id", flat=True))
        if not allowed_ids and getattr(self.user, "is_superuser", False):
            return ApplicationField.get_for_model(self.model).order_by("field")
        return ApplicationField.objects.filter(id__in=allowed_ids).order_by("field")

    def get_allowed_field_names(self) -> list[str]:
        """
        Get the field names that the user is allowed to access for this service's model.
        """
        allowed_names: list[str] = []
        for application_field in self.get_allowed_application_fields():
            field_name = application_field.field
            if field_name in AUTO_MANAGED_FIELD_NAMES:
                continue
            try:
                model_field = application_field._get_model_field()
            except Exception:
                continue
            if not getattr(model_field, "editable", True):
                continue
            if not getattr(model_field, "concrete", True):
                continue
            if application_field.get_form_field() is None:
                continue
            allowed_names.append(field_name)
        return allowed_names

    def build_template_form(self, data=None) -> BloomerpDownloadBulkUploadTemplateForm:
        """
        Build the template form for the bulk upload process.

        Args:
            data: Optional data to populate the form.

        Returns:
            BloomerpDownloadBulkUploadTemplateForm: The form instance.
        """
        return BloomerpDownloadBulkUploadTemplateForm(
            content_type=self.content_type,
            application_fields=self.get_allowed_application_fields(),
            data=data,
        )

    def create_template_bytes(self, *, fields: list[str], file_type: str) -> tuple[bytes, str, str]:
        """
        Create the template bytes for the bulk upload process.

        Args:
            fields: The fields to include in the template.
            file_type: The type of file to create ("csv" or "xlsx").

        Returns:
            tuple[bytes, str, str]: The template bytes, content type, and file extension.
        """
        allowed_names = set(self.get_allowed_field_names())
        selected_fields = [field for field in fields if field in allowed_names]
        if not selected_fields:
            raise ValidationError("Select at least one permitted field.")

        template_bytes = self.model_io.create_model_template(file_type=file_type, fields=selected_fields)
        if file_type == "csv":
            content_type = "text/csv"
            extension = "csv"
        elif file_type == "xlsx":
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = "xlsx"
        else:
            raise ValidationError("Invalid export format.")

        return template_bytes, content_type, extension

    def create_template_filename(self, extension: str) -> str:
        """
        Create the filename for the bulk upload template.

        Args:
            extension: The file extension.

        Returns:
            str: The filename.
        """
        return f"{self.model.__name__}__bulk_upload_template.{extension}"

    def create_draft(self, uploaded_file, *, previous_file_id: str | None = None) -> BulkUploadDraft:
        """Create a bulk upload draft from an uploaded file.

        Args:
            uploaded_file: The uploaded file.
            previous_file_id: The ID of the previous draft file, if any.

        Returns:
            BulkUploadDraft: The created bulk upload draft.
        """
        if uploaded_file is None:
            raise ValidationError("Upload a CSV or Excel file.")

        self.delete_draft_file(previous_file_id)

        draft_file = File(
            file=uploaded_file,
            name=getattr(uploaded_file, "name", None) or "bulk-upload",
            content_type=self.content_type,
            persisted=False,
            created_by=self.user,
            updated_by=self.user,
            meta={
                "bulk_upload_draft": True,
                "content_type_id": self.content_type.pk,
                "model_label": self.model._meta.label_lower,
                "original_filename": getattr(uploaded_file, "name", "") or "",
                "upload_type": "bulk_upload",
            },
        )
        draft_file.save()

        try:
            rows, selected_fields = self.get_source_rows(draft_file.pk)
        except Exception:
            draft_file.delete()
            raise

        return BulkUploadDraft(
            file_id=str(draft_file.pk),
            selected_fields=selected_fields,
            total_rows=len(rows),
            original_filename=str(getattr(uploaded_file, "name", "") or draft_file.name or ""),
        )

    def get_draft_file(self, file_id: str | None) -> File | None:
        """Get the draft file for a given file ID."""
        if not file_id:
            return None
        return File.objects.filter(pk=file_id, meta__bulk_upload_draft=True).first()

    def delete_draft_file(self, file_id: str | None) -> None:
        """Delete the draft file for a given file ID."""
        draft_file = self.get_draft_file(file_id)
        if draft_file is not None:
            draft_file.delete()

    def load_dataframe(self, file_id: str | File) -> pd.DataFrame:
        """Load the uploaded file into a pandas DataFrame."""
        draft_file = file_id if isinstance(file_id, File) else self.get_draft_file(file_id)
        if draft_file is None or not getattr(draft_file, "file", None):
            raise ValidationError("The uploaded draft file could not be found.")

        draft_file.file.open("rb")
        try:
            filename = (draft_file.file.name or draft_file.name or "").lower()
            if filename.endswith(".csv"):
                dataframe = pd.read_csv(TextIOWrapper(draft_file.file.file, encoding="utf-8"))
            elif filename.endswith((".xlsx", ".xls")):
                dataframe = pd.read_excel(draft_file.file.file)
            else:
                raise ValidationError("Unsupported file type. Only CSV and Excel files are allowed.")
        finally:
            draft_file.file.close()

        return self._normalize_dataframe_headers(dataframe)

    def get_source_rows(self, file_id: str | File) -> tuple[list[dict[str, Any]], list[str]]:
        """Get the source rows from the uploaded file.

        Args:
            file_id: The ID of the uploaded file or a File instance.

        Returns:
            tuple[list[dict[str, Any]], list[str]]: The source rows and selected fields.
        """
        dataframe = self.load_dataframe(file_id)
        selected_fields = self.validate_dataframe_headers(dataframe)
        records: list[dict[str, Any]] = []
        for row in dataframe[selected_fields].to_dict(orient="records"):
            records.append(
                {
                    field_name: self.serialize_cell_value(row.get(field_name))
                    for field_name in selected_fields
                }
            )
        return records, selected_fields

    def build_review_page(
        self,
        *,
        file_id: str,
        changes: dict[str, dict[str, Any]] | None,
        page: int,
        page_size: int = DEFAULT_REVIEW_PAGE_SIZE,
        data=None,
    ) -> BulkUploadReviewPage:
        """Build the review page for the bulk upload process.

        Args:
            file_id: The ID of the uploaded file.
            changes: The changes to apply to the rows.
            page: The page number.
            page_size: The number of rows per page.
            data: Optional data to populate the formset.

        Returns:
            BulkUploadReviewPage: The review page instance.
        """
        source_rows, fields = self.get_source_rows(file_id)
        effective_rows = self.apply_changes_to_rows(rows=source_rows, changes=changes or {})
        ordered_row_indexes, all_row_errors = self.get_review_order(rows=effective_rows, fields=fields)
        total_rows = len(source_rows)
        total_pages = max((total_rows - 1) // page_size + 1, 1)
        page = min(max(page, 1), total_pages)
        start_index = (page - 1) * page_size
        end_index = min(start_index + page_size, total_rows)
        page_row_indexes = ordered_row_indexes[start_index:end_index]
        page_rows = [
            (row_index, deepcopy(effective_rows[row_index]))
            for row_index in page_row_indexes
        ]

        formset_class = self.get_review_formset_class(fields=fields)
        initial = [
            {
                "row_index": row_index,
                **row_data,
            }
            for row_index, row_data in page_rows
        ]
        if data is None:
            formset = formset_class(initial=initial, prefix="review")
        else:
            formset = formset_class(data=data, prefix="review")

        page_row_errors: dict[int, dict[str, list[str]]] = {
            row_index: all_row_errors[row_index]
            for row_index in page_row_indexes
            if row_index in all_row_errors
        }
        invalid_row_indexes: list[str] = [str(row_index) for row_index in page_row_indexes if row_index in all_row_errors]

        return BulkUploadReviewPage(
            formset=formset,
            fields=fields,
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=total_pages,
            start_row=start_index + 1 if total_rows else 0,
            end_row=end_index,
            page_row_errors=page_row_errors,
            invalid_row_indexes=invalid_row_indexes,
            ordered_row_indexes=ordered_row_indexes,
        )

    def merge_page_changes(
        self,
        *,
        file_id: str,
        changes: dict[str, dict[str, Any]] | None,
        formset: BaseFormSet,
    ) -> dict[str, dict[str, Any]]:
        """
        Merge the changes from the review page formset into the existing changes.

        Example: If the original changes are `{"3": {"name": "Alice"}}` and the formset contains a change to row 3 that updates the name to "Alicia" and adds an email, the merged changes would be `{"3": {"name": "Alicia", "email": "alice@example.com"}}`.

        Args:
            file_id: The ID of the uploaded file.
            changes: The existing changes to merge into.
            formset: The formset containing the new changes.

        Returns:
            dict[str, dict[str, Any]]: The merged changes.
        """
        source_rows, fields = self.get_source_rows(file_id)
        current_changes = deepcopy(changes or {})
        source_lookup = {row_index: row for row_index, row in enumerate(source_rows)}

        for form in formset.forms:
            row_index = int(form.cleaned_data["row_index"])
            source_row = source_lookup.get(row_index)
            if source_row is None:
                continue

            row_changes = current_changes.get(str(row_index), {}).copy()
            for field_name in fields:
                new_value = self.serialize_form_value(form.cleaned_data.get(field_name))
                source_value = self.serialize_form_value(source_row.get(field_name))
                if self.values_match(new_value, source_value):
                    row_changes.pop(field_name, None)
                else:
                    row_changes[field_name] = new_value

            if row_changes:
                current_changes[str(row_index)] = row_changes
            else:
                current_changes.pop(str(row_index), None)

        return current_changes

    def build_validation_summary(
        self,
        *,
        file_id: str,
        changes: dict[str, dict[str, Any]] | None,
    ) -> BulkUploadValidationSummary:
        """Validate the effective draft rows and summarize validation results.

        Args:
            file_id (str): Identifier of the stored draft file.
            changes (dict[str, dict[str, Any]] | None): Sparse row and field edits
                collected during the wizard review step.

        Returns:
            BulkUploadValidationSummary: Summary describing row counts and sampled
            validation errors.
        """
        rows, fields = self.get_source_rows(file_id)
        effective_rows = self.apply_changes_to_rows(rows=rows, changes=changes or {})
        form_class = self.get_review_model_form_class(fields=fields)

        errors: list[dict[str, Any]] = []
        valid_rows = 0

        for row_index, row_data in enumerate(effective_rows):
            form = form_class(data=self.row_to_querydict(row_data))
            if form.is_valid():
                valid_rows += 1
                continue

            if len(errors) < MAX_VALIDATION_ERRORS:
                errors.append(
                    {
                        "row": row_index + 1,
                        "errors": self.flatten_form_errors(form.errors),
                    }
                )

        total_rows = len(effective_rows)
        invalid_rows = total_rows - valid_rows
        return BulkUploadValidationSummary(
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            errors=errors,
        )

    def process_draft(self, *, file_id: str, changes: dict[str, dict[str, Any]] | None) -> tuple[str, int]:
        """Process a reviewed bulk upload draft.

        Args:
            file_id (str): Identifier of the stored draft file.
            changes (dict[str, dict[str, Any]] | None): Sparse row and field edits
                collected during the wizard review step.

        Returns:
            tuple[str, int]: A tuple of ``(status, count)`` where ``status`` is
            ``queued`` or ``completed``, and ``count`` is either the queued row
            count or the number of created objects.
        """
        if is_celery_available():
            try:
                from bloomerp.tasks.bulk_upload_task import process_bulk_upload_submission

                process_bulk_upload_submission.delay(
                    content_type_id=self.content_type.pk,
                    user_id=self.user.pk,
                    file_id=file_id,
                    changes=changes or {},
                )
                total_rows = self.build_validation_summary(file_id=file_id, changes=changes).total_rows
                return "queued", total_rows
            except Exception:
                pass

        created_count = self._process_draft_impl(file_id=file_id, changes=changes)
        return "completed", created_count

    def _process_draft_impl(self, *, file_id: str, changes: dict[str, dict[str, Any]] | None) -> int:
        """Execute the bulk draft import synchronously.

        Args:
            file_id (str): Identifier of the stored draft file.
            changes (dict[str, dict[str, Any]] | None): Sparse row and field edits
                collected during the wizard review step.

        Returns:
            int: Number of objects created from the effective draft rows.
        """
        # TODO: Add support for async success messages
        rows, fields = self.get_source_rows(file_id)
        effective_rows = self.apply_changes_to_rows(rows=rows, changes=changes or {})
        summary = self.build_validation_summary(file_id=file_id, changes=changes)
        if not summary.is_valid:
            raise ValidationError("The uploaded data contains validation errors.")

        form_class = self.get_review_model_form_class(fields=fields)
        created_count = 0

        with transaction.atomic():
            for row_data in effective_rows:
                form = form_class(data=self.row_to_querydict(row_data))
                if not form.is_valid():
                    raise ValidationError("The uploaded data contains validation errors.")

                instance = form.save(commit=False)
                if hasattr(instance, "created_by") and getattr(instance, "created_by", None) is None:
                    instance.created_by = self.user
                if hasattr(instance, "updated_by"):
                    instance.updated_by = self.user
                instance.save()
                if hasattr(form, "save_m2m"):
                    form.save_m2m()
                created_count += 1

        return created_count

    def get_review_model_form_class(self, *, fields: list[str]):
        base_form_class = bloomerp_modelform_factory(self.model, fields=fields)

        class ReviewModelForm(base_form_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for bound_name, field in self.fields.items():
                    widget = field.widget
                    if isinstance(widget, (HiddenInput, CheckboxInput, CheckboxSelectMultiple, RadioSelect)):
                        continue

                    existing_class = str(widget.attrs.get("class", "") or "").strip()
                    class_names = existing_class.split() if existing_class else []
                    if "input" not in class_names:
                        class_names.append("input")
                    widget.attrs["class"] = " ".join(class_names).strip()

        return ReviewModelForm

    def get_review_formset_class(self, *, fields: list[str]):
        base_form_class = self.get_review_model_form_class(fields=fields)
        review_form_class = type(
            f"{self.model.__name__}BulkUploadReviewForm",
            (base_form_class,),
            {
                "row_index": forms.IntegerField(widget=forms.HiddenInput()),
            },
        )
        return formset_factory(review_form_class, extra=0)

    def validate_dataframe_headers(self, dataframe: pd.DataFrame) -> list[str]:
        allowed_by_lower = {field_name.lower(): field_name for field_name in self.get_allowed_field_names()}
        selected_fields: list[str] = []
        invalid_fields: list[str] = []

        for column in dataframe.columns:
            column_name = str(column).strip()
            canonical_name = allowed_by_lower.get(column_name.lower())
            if canonical_name is None:
                invalid_fields.append(column_name)
                continue
            selected_fields.append(canonical_name)

        if invalid_fields:
            raise ValidationError(
                "You do not have permission to bulk upload the following fields: "
                + ", ".join(sorted(invalid_fields))
            )
        if not selected_fields:
            raise ValidationError("The uploaded file did not contain any permitted columns.")

        return selected_fields

    def apply_changes_to_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        changes: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        effective_rows = deepcopy(rows)
        for row_index_str, row_changes in (changes or {}).items():
            try:
                row_index = int(row_index_str)
            except (TypeError, ValueError):
                continue
            if 0 <= row_index < len(effective_rows):
                effective_rows[row_index].update(row_changes)
        return effective_rows

    def serialize_form_value(self, value):
        if isinstance(value, Model):
            return str(value.pk)
        if isinstance(value, QuerySet):
            return [str(pk) for pk in value.values_list("pk", flat=True)]
        if isinstance(value, (list, tuple, set)):
            return [self.serialize_form_value(item) for item in value]
        return self.serialize_cell_value(value)

    def serialize_cell_value(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, float) and pd.isna(value):
            return ""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        return str(value)

    def row_to_querydict(self, row_data: dict[str, Any]) -> QueryDict:
        querydict = QueryDict("", mutable=True)
        for key, value in row_data.items():
            if isinstance(value, list):
                querydict.setlist(key, [str(item) for item in value])
            elif isinstance(value, bool):
                if value:
                    querydict[key] = "on"
            elif value not in ("", None):
                querydict[key] = str(value)
        return querydict

    def flatten_form_errors(self, form_errors) -> list[str]:
        messages: list[str] = []
        for field_name, error_list in form_errors.items():
            label = field_name if field_name != "__all__" else "Row"
            for error in error_list:
                messages.append(f"{label}: {error}")
        return messages

    def serialize_form_errors(self, form_errors) -> dict[str, list[str]]:
        serialized: dict[str, list[str]] = {}
        for field_name, error_list in form_errors.items():
            serialized[str(field_name)] = [str(error) for error in error_list]
        return serialized

    def get_review_order(
        self,
        *,
        rows: list[dict[str, Any]],
        fields: list[str],
    ) -> tuple[list[int], dict[int, dict[str, list[str]]]]:
        validation_form_class = self.get_review_model_form_class(fields=fields)
        invalid_indexes: list[int] = []
        valid_indexes: list[int] = []
        row_errors: dict[int, dict[str, list[str]]] = {}

        for row_index, row_data in enumerate(rows):
            validation_form = validation_form_class(data=self.row_to_querydict(row_data))
            if validation_form.is_valid():
                valid_indexes.append(row_index)
                continue

            invalid_indexes.append(row_index)
            row_errors[row_index] = self.serialize_form_errors(validation_form.errors)
            non_field_errors = [str(error) for error in validation_form.non_field_errors()]
            if non_field_errors:
                row_errors[row_index]["__all__"] = non_field_errors

        return invalid_indexes + valid_indexes, row_errors

    def values_match(self, left, right) -> bool:
        if isinstance(left, list) or isinstance(right, list):
            return list(left or []) == list(right or [])
        return left == right

    def _apply_changes_to_page_rows(
        self,
        *,
        start_index: int,
        source_rows: list[dict[str, Any]],
        changes: dict[str, dict[str, Any]],
    ) -> list[tuple[int, dict[str, Any]]]:
        page_rows: list[tuple[int, dict[str, Any]]] = []
        for offset, source_row in enumerate(source_rows):
            row_index = start_index + offset
            row_data = deepcopy(source_row)
            row_data.update((changes or {}).get(str(row_index), {}))
            page_rows.append((row_index, row_data))
        return page_rows

    def _normalize_dataframe_headers(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        normalized = dataframe.copy()
        normalized.columns = [str(column).strip() for column in normalized.columns]
        normalized = normalized.fillna("")
        return normalized


def wrap_template_bytes(template_bytes: bytes) -> BytesIO:
    stream = BytesIO(template_bytes)
    stream.seek(0)
    return stream
