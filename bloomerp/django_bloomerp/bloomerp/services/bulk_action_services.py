from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import modelform_factory
from django.db import models

from bloomerp.models import ApplicationField
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str


class BulkActionService:
    def __init__(self, *, model: type[models.Model], user):
        self.model = model
        self.user = user
        self.permission_manager = UserPermissionManager(user)

    @classmethod
    def from_content_type_id(cls, *, content_type_id: int, user) -> "BulkActionService":
        content_type = ContentType.objects.get(pk=content_type_id)
        model = content_type.model_class()
        if model is None:
            raise ValueError("Invalid content type")
        return cls(model=model, user=user)

    def update_field(
        self,
        *,
        application_field: ApplicationField,
        object_ids: list[str],
        value: Any,
    ) -> int:
        bulk_permission = create_permission_str(self.model, "bulk_change")
        change_permission = create_permission_str(self.model, "change")

        if not self.permission_manager.has_global_permission(self.model, bulk_permission):
            raise PermissionDenied("Permission denied")
        if not self.permission_manager.has_field_permission(application_field, change_permission):
            raise PermissionDenied("Permission denied")

        queryset = self.permission_manager.get_queryset(self.model, bulk_permission).filter(pk__in=object_ids)
        field_name = application_field.field
        form_field = application_field.get_form_field()
        if form_field is None:
            raise ValidationError("Invalid field")

        form_cls = modelform_factory(self.model, fields=[field_name])
        updated_count = 0
        for obj in queryset:
            form = form_cls(data={field_name: value}, instance=obj)
            if not form.is_valid():
                raise ValidationError(form.errors)
            form.save()
            updated_count += 1

        return updated_count
