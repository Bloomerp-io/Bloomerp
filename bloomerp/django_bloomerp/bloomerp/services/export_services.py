from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from uuid import UUID

import openpyxl
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Model, QuerySet
from django.db.models.fields.files import FieldFile

from bloomerp.models.application_field import ApplicationField
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.filters import filter_model

MULTI_VALUE_SEPARATOR = ";"


class ExportService:
    def __init__(self, model: type[Model], user, *, permission_str: str):
        self.model = model
        self.user = user
        self.permission_str = permission_str
        self.content_type = ContentType.objects.get_for_model(model)
        self.permission_manager = UserPermissionManager(user)

    @classmethod
    def from_content_type_id(cls, content_type_id: int, user, *, permission_str: str) -> "ExportService":
        content_type = ContentType.objects.get(id=content_type_id)
        model = content_type.model_class()
        if model is None:
            raise ValidationError("Invalid content type.")
        return cls(model=model, user=user, permission_str=permission_str)

    def create_export_bytes(
        self,
        *,
        application_fields: QuerySet[ApplicationField] | list[ApplicationField],
        file_type: str,
        query_params=None,
    ) -> tuple[bytes, str, str]:
        selected_fields = self.get_selected_application_fields(application_fields)
        queryset = self.build_queryset(query_params=query_params)

        if file_type == "csv":
            return self._export_to_csv(queryset=queryset, fields=selected_fields), "text/csv", "csv"
        if file_type == "xlsx":
            return (
                self._export_to_excel(queryset=queryset, fields=selected_fields),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
            )

        raise ValidationError("Invalid export format.")

    def create_export_filename(self, extension: str) -> str:
        return f"{self.model.__name__}__export.{extension}"

    def get_selected_application_fields(
        self,
        application_fields: QuerySet[ApplicationField] | list[ApplicationField],
    ) -> list[ApplicationField]:
        if isinstance(application_fields, QuerySet):
            selected_fields = list(application_fields)
        else:
            selected_fields = list(application_fields)

        selected_fields = [application_field for application_field in selected_fields if application_field.field]
        if not selected_fields:
            raise ValidationError("Select at least one permitted field.")
        return selected_fields

    def build_queryset(self, *, query_params=None) -> QuerySet:
        queryset = self.permission_manager.get_queryset(self.model, self.permission_str)
        if query_params is None:
            return queryset

        query = query_params.get("q")
        if query:
            queryset = string_search_on_queryset(queryset, query)

        return filter_model(self.model, query_params, queryset)

    def _export_to_csv(self, *, queryset: QuerySet, fields: list[ApplicationField]) -> bytes:
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow([application_field.field for application_field in fields])

        for obj in queryset.iterator():
            writer.writerow([self._serialize_application_field_value(obj, application_field) for application_field in fields])

        contents = buffer.getvalue()
        buffer.close()
        return contents.encode("utf-8")

    def _export_to_excel(self, *, queryset: QuerySet, fields: list[ApplicationField]) -> bytes:
        buffer = BytesIO()
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append([application_field.field for application_field in fields])

        for obj in queryset.iterator():
            sheet.append([self._serialize_application_field_value(obj, application_field) for application_field in fields])

        workbook.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    def _serialize_application_field_value(self, obj: Model, application_field: ApplicationField):
        try:
            model_field = application_field._get_model_field()
        except FieldDoesNotExist:
            return self._serialize_value(getattr(obj, application_field.field, ""))

        if getattr(model_field, "one_to_many", False):
            relation_attr = application_field.field
            if not hasattr(obj, relation_attr) and hasattr(model_field, "get_accessor_name"):
                relation_attr = model_field.get_accessor_name()
            related_manager = getattr(obj, relation_attr)
            return MULTI_VALUE_SEPARATOR.join(
                str(value)
                for value in related_manager.values_list("pk", flat=True)
            )

        if model_field.many_to_many:
            manager = getattr(obj, application_field.field)
            return MULTI_VALUE_SEPARATOR.join(
                str(value)
                for value in manager.values_list("pk", flat=True)
            )

        value = model_field.value_from_object(obj)
        return self._serialize_value(value)

    def _serialize_value(self, value):
        if value is None:
            return ""
        if isinstance(value, FieldFile):
            return value.name or ""
        if isinstance(value, bool):
            return value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value


def wrap_export_bytes(export_bytes: bytes) -> BytesIO:
    stream = BytesIO(export_bytes)
    stream.seek(0)
    return stream
