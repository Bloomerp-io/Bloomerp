from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from django.contrib.contenttypes.models import ContentType

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    clamp_layout_colspan,
    get_object_field_value,
)


class BloomerpLayoutFormMixin(ABC):
    template_name = "mixins/bloomerp_layout_form_mixin.html"
    layout_mode = "detail"

    @abstractmethod
    def get_layout_object(self) -> FieldLayout:
        raise NotImplementedError

    def is_create_layout(self) -> bool:
        return self.layout_mode == "create"

    def get_layout_mode(self) -> str:
        return self.layout_mode

    def get_layout_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(self.model)

    def get_layout_content_type_id(self) -> int:
        return self.get_layout_content_type().pk

    def get_layout_permission_manager(self) -> UserPermissionManager | None:
        user = getattr(getattr(self, "request", None), "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        return UserPermissionManager(user)

    def get_layout_view_permission(self) -> str:
        action = "add" if self.is_create_layout() else "view"
        return create_permission_str(self.model, action)

    def get_layout_edit_permission(self) -> str:
        return create_permission_str(self.model, "change")

    def get_layout_render_item_url(self) -> str:
        return "/components/workspaces/crud_layout_render_field/"

    def get_layout_available_items_url(self) -> str:
        return ""

    def get_layout_save_url(self) -> str:
        return ""

    def get_non_required_fields_visible_default(self) -> bool:
        return True

    def get_non_required_fields_visible_attr(self) -> str:
        return "true" if self.get_non_required_fields_visible_default() else "false"

    def can_change_layout(self) -> bool:
        return False

    def get_layout_context_extras(self, *, layout: FieldLayout, form=None) -> dict[str, Any]:
        return {}

    def get_layout_bound_object(self):
        return getattr(self, "object", None)

    def get_layout_editable_field_names(self) -> list[str]:
        return []

    def build_layout_form(self):
        field_names = self.get_layout_editable_field_names()
        if not field_names:
            return None

        form_class = bloomerp_modelform_factory(self.model, fields=field_names)
        kwargs: dict[str, Any] = {}
        bound_object = self.get_layout_bound_object()
        if bound_object is not None:
            kwargs["instance"] = bound_object

        if getattr(getattr(self, "request", None), "method", "").upper() == "POST":
            kwargs["data"] = self.request.POST
            kwargs["files"] = self.request.FILES

        form = form_class(**kwargs)
        for field_name in ("updated_by", "created_by"):
            if field_name in form.fields:
                del form.fields[field_name]
        return form

    def get_layout_form(self, *, context: dict[str, Any] | None = None):
        if context and context.get("layout_form") is not None:
            return context["layout_form"]
        if context and context.get("form") is not None and self.is_create_layout():
            return context["form"]
        return self.build_layout_form()

    def normalize_layout_application_field_id(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def get_layout_application_fields(self, *, layout: FieldLayout) -> dict[int, ApplicationField]:
        item_ids = [
            normalized_id
            for row in layout.rows
            for item in row.items
            if (normalized_id := self.normalize_layout_application_field_id(item.id)) is not None
        ]
        if not item_ids:
            return {}

        content_type = self.get_layout_content_type()
        fields = ApplicationField.objects.filter(content_type=content_type, id__in=item_ids)
        return {field.pk: field for field in fields}

    def can_view_application_field(self, application_field: ApplicationField) -> bool:
        manager = self.get_layout_permission_manager()
        if manager is None:
            return True
        return manager.has_field_permission(application_field, self.get_layout_view_permission())

    def can_edit_application_field(self, application_field: ApplicationField) -> bool:
        manager = self.get_layout_permission_manager()
        if manager is None:
            return False
        return manager.has_field_permission(application_field, self.get_layout_edit_permission())

    def build_layout_item_context(
        self,
        *,
        application_field: ApplicationField,
        colspan: int,
        form=None,
    ) -> dict[str, Any] | None:
        if not self.can_view_application_field(application_field):
            return None

        bound_object = self.get_layout_bound_object()
        has_bound_field = bool(form and application_field.field in form.fields)
        can_edit = has_bound_field and self.can_edit_application_field(application_field)

        if has_bound_field:
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                bound_field=form[application_field.field],
                can_edit=True,
            )
        elif bound_object is not None:
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                value=get_object_field_value(obj=bound_object, application_field=application_field),
                can_edit=False,
            )
        else:
            return None

        return {
            "id": application_field.pk,
            "colspan": colspan,
            "can_edit": can_edit,
            **field_context,
        }

    def get_layout_rows(self, *, layout: FieldLayout, form=None) -> list[dict[str, Any]]:
        application_fields = self.get_layout_application_fields(layout=layout)
        rows: list[dict[str, Any]] = []

        for row in layout.rows:
            items: list[dict[str, Any]] = []
            for item in row.items:
                item_id = self.normalize_layout_application_field_id(item.id)
                if item_id is None:
                    continue

                application_field = application_fields.get(item_id)
                if application_field is None:
                    continue

                item_context = self.build_layout_item_context(
                    application_field=application_field,
                    colspan=clamp_layout_colspan(item.colspan, row.columns),
                    form=form,
                )
                if item_context is None:
                    continue

                items.append(item_context)

            rows.append(
                {
                    "title": row.title,
                    "columns": row.columns,
                    "items": items,
                }
            )

        return rows

    def build_layout_context(self, *, form=None) -> dict[str, Any]:
        layout_object = self.get_layout_object()
        layout = {
            "rows": self.get_layout_rows(
                layout=layout_object,
                form=form,
            )
        }

        context = {
            "content_type_id": self.get_layout_content_type_id(),
            "layout_object": layout_object,
            "layout": layout,
            "layout_mode": self.get_layout_mode(),
            "layout_available_items_url": self.get_layout_available_items_url(),
            "layout_save_url": self.get_layout_save_url(),
            "can_change_layout": self.can_change_layout(),
            "layout_render_item_url": self.get_layout_render_item_url(),
            "layout_is_create": self.is_create_layout(),
            "non_required_fields_visible_attr": self.get_non_required_fields_visible_attr(),
        }
        context.update(self.get_layout_context_extras(layout=layout_object, form=form))
        return context

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        explicit_layout_form = kwargs.pop("_layout_form", None)
        context = super().get_context_data(**kwargs)
        form = explicit_layout_form or self.get_layout_form(context=context)
        context["layout_has_form"] = form is not None
        context["layout_non_field_errors"] = list(form.non_field_errors()) if form is not None else []
        context.update(self.build_layout_context(form=form))
        return context
