from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.forms import MultiWidget, modelform_factory

from bloomerp.models import ApplicationField
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


class BulkActionService:
    def __init__(self, *, model: type[models.Model], user):
        self.model = model
        self.user = user
        self.permission_manager = UserPolicyManager(user)

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
        """Update permitted rows using model forms, including multipart widgets."""
        if not self.permission_manager.has_global_permission(
            self.model,
            BloomerpPermission.BULK_CHANGE,
        ):
            raise PermissionDenied("Permission denied")
        if not self.permission_manager.has_field_permission(
            application_field,
            BloomerpPermission.CHANGE,
        ):
            raise PermissionDenied("Permission denied")

        queryset = self.permission_manager.get_accessible_queryset(
            self.model,
            BloomerpPermission.BULK_CHANGE,
        ).filter(pk__in=object_ids)
        field_name = application_field.field
        form_field = application_field.get_form_field()
        if form_field is None:
            raise ValidationError("Invalid field")

        form_cls = modelform_factory(self.model, fields=[field_name])
        form_data = {field_name: value}
        model_form_field = form_cls.base_fields[field_name]
        widget = model_form_field.widget
        if isinstance(widget, MultiWidget):
            # ModelForm reads multipart inputs through the widget, not the root key.
            # Clean first so invalid mappings/JSON cannot silently become empty.
            parts = widget.decompress(model_form_field.clean(value))
            form_data = {
                f"{field_name}{suffix}": part
                for suffix, part in zip(widget.widgets_names, parts)
            }
        updated_count = 0
        
        # TODO: Change to bulk change
        for obj in queryset:
            form = form_cls(data=form_data, instance=obj)
            if not form.is_valid():
                raise ValidationError(form.errors)
            form.save()
            updated_count += 1
        
        return updated_count

    @transaction.atomic
    def delete_objects(self, *, object_ids: list[str]) -> int:
        """Delete the permitted objects while preserving model delete hooks."""
        if not self.permission_manager.has_global_permission(
            self.model,
            BloomerpPermission.BULK_DELETE,
        ):
            raise PermissionDenied("Permission denied")

        queryset = self.permission_manager.get_accessible_queryset(
            self.model,
            BloomerpPermission.BULK_DELETE,
        ).filter(pk__in=object_ids)
        objects = list(queryset)

        for obj in objects:
            obj.delete()

        return len(objects)


def execute_bulk_update(
    *,
    content_type_id: int,
    user_id: int,
    application_field_id: int,
    object_ids: list[str],
    value: Any,
) -> int:
    """Run a permission-checked bulk update from serialized identifiers."""
    user = get_user_model().objects.get(pk=user_id)
    application_field = ApplicationField.objects.get(pk=application_field_id)
    service = BulkActionService.from_content_type_id(
        content_type_id=content_type_id,
        user=user,
    )
    return service.update_field(
        application_field=application_field,
        object_ids=object_ids,
        value=value,
    )


def execute_bulk_delete(
    *,
    content_type_id: int,
    user_id: int,
    object_ids: list[str],
) -> int:
    """Run a permission-checked bulk delete from serialized identifiers."""
    user = get_user_model().objects.get(pk=user_id)
    service = BulkActionService.from_content_type_id(
        content_type_id=content_type_id,
        user=user,
    )
    return service.delete_objects(object_ids=object_ids)
