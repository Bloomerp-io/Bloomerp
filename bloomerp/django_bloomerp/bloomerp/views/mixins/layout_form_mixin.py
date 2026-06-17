from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.one_to_many_field_services import collect_submitted_one_to_many_data
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import build_crud_layout_field_context, clamp_layout_colspan, get_object_field_value


from django.contrib.contenttypes.models import ContentType


from abc import ABC, abstractmethod
from typing import Any


class BloomerpLayoutFormMixin(ABC):
    template_name = "mixins/bloomerp_layout_form_mixin.html"
    layout_mode = "detail"
    no_submitted_layout_value = object()

    @abstractmethod
    def get_layout_object(self) -> FieldLayout:
        raise NotImplementedError

    def get_layout_preference_object(self):
        return None

    def is_create_layout(self) -> bool:
        return self.layout_mode == "create"

    def get_layout_mode(self) -> str:
        return self.layout_mode

    def get_layout_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(self.model)

    def get_layout_content_type_id(self) -> int:
        return self.get_layout_content_type().pk

    def get_layout_object_content_type(self) -> ContentType:
        layout_preference_object = self.get_layout_preference_object()
        target = layout_preference_object if layout_preference_object is not None else self.get_layout_bound_object()
        if target is None:
            raise ValueError("Layout object content type requires a layout-backed object")
        return ContentType.objects.get_for_model(target.__class__)

    def get_layout_object_content_type_id(self) -> int:
        return self.get_layout_object_content_type().pk

    def get_layout_object_id(self):
        layout_preference_object = self.get_layout_preference_object()
        target = layout_preference_object if layout_preference_object is not None else self.get_layout_bound_object()
        return getattr(target, "pk", None)

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
        return ""

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

    def can_delete_layout_object(self) -> bool:
        return self.can_change_layout()

    def get_layout_context_extras(self, *, layout: FieldLayout, form=None) -> dict[str, Any]:
        return {}

    def get_layout_bound_object(self):
        return getattr(self, "object", None)

    def get_layout_parent_model(self):
        return self.model

    def get_layout_editable_field_names(self) -> list[str]:
        return []

    def get_one_to_many_submitted_data_source(self):
        if getattr(getattr(self, "request", None), "method", "").upper() == "POST":
            return self.request.POST
        return None

    def get_submitted_one_to_many_values(self) -> dict[str, list[dict]]:
        if hasattr(self, "_submitted_one_to_many_values"):
            return self._submitted_one_to_many_values

        submitted_data = self.get_one_to_many_submitted_data_source()
        if submitted_data is None:
            self._submitted_one_to_many_values = {}
            return self._submitted_one_to_many_values

        self._submitted_one_to_many_values = collect_submitted_one_to_many_data(
            parent_model=self.get_layout_parent_model(),
            layout=self.get_layout_object(),
            submitted_data=submitted_data,
        )
        return self._submitted_one_to_many_values

    def get_submitted_layout_field_value(self, application_field: ApplicationField):
        field_type = application_field.get_field_type_enum().value
        if field_type.id != "OneToManyField":
            return self.no_submitted_layout_value

        submitted_values = self.get_submitted_one_to_many_values()
        if application_field.field not in submitted_values:
            return self.no_submitted_layout_value
        return submitted_values[application_field.field]

    def get_layout_visible_field_names(self) -> set[str]:
        layout = self.get_layout_object()
        application_fields = self.get_layout_application_fields(layout=layout)
        visible_field_names: set[str] = set()
        for row in layout.rows:
            for item in row.items:
                item_id = self.normalize_layout_application_field_id(item.id)
                if item_id is None:
                    continue
                application_field = application_fields.get(item_id)
                if application_field is None:
                    continue
                visible_field_names.add(application_field.field)
        return visible_field_names

    def add_hidden_current_value_to_data(self, *, data, field_name: str, form_field, current_value) -> None:
        if hasattr(current_value, "all"):
            data.setlist(field_name, [str(obj.pk) for obj in current_value.all()])
            return

        prepared_value = (
            form_field.prepare_value(current_value)
            if form_field is not None
            else current_value
        )
        if isinstance(prepared_value, (list, tuple, set)):
            data.setlist(field_name, [str(value) for value in prepared_value])
            return

        data[field_name] = prepared_value

    def build_layout_form(self):
        field_names = self.get_layout_editable_field_names()
        if not field_names:
            return None

        form_class = bloomerp_modelform_factory(self.model, fields=field_names)
        form_fields = form_class.base_fields
        kwargs: dict[str, Any] = {}
        bound_object = self.get_layout_bound_object()
        if bound_object is not None:
            kwargs["instance"] = bound_object

        if getattr(getattr(self, "request", None), "method", "").upper() == "POST":
            data = self.request.POST.copy()
            if not self.is_create_layout() and bound_object is not None:
                visible_field_names = self.get_layout_visible_field_names()
                for field_name in field_names:
                    if field_name in visible_field_names or field_name in data:
                        continue
                    current_value = getattr(bound_object, field_name, None)
                    if current_value not in (None, ""):
                        form_field = form_fields.get(field_name)
                        self.add_hidden_current_value_to_data(
                            data=data,
                            field_name=field_name,
                            form_field=form_field,
                            current_value=current_value,
                        )
            kwargs["data"] = data
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

    def can_render_unbound_editable_layout_field(self, application_field: ApplicationField) -> bool:
        return self.is_create_layout()

    def get_unbound_layout_field_value(self, application_field: ApplicationField):
        return None

    def build_layout_item_context(
        self,
        *,
        application_field: ApplicationField,
        colspan: int,
        config: dict[str, Any] | None = None,
        form=None,
    ) -> dict[str, Any] | None:
        if not self.can_view_application_field(application_field):
            return None

        bound_object = self.get_layout_bound_object()
        has_bound_field = bool(form and application_field.field in form.fields)
        has_edit_permission = self.can_edit_application_field(application_field)
        field_type = application_field.get_field_type_enum().value
        can_edit = has_bound_field and has_edit_permission
        submitted_value = self.get_submitted_layout_field_value(application_field)

        if has_bound_field:
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                bound_field=form[application_field.field],
                can_edit=True,
                layout_config=config,
            )
        elif submitted_value is not self.no_submitted_layout_value:
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                value=submitted_value,
                can_edit=(
                    has_edit_permission
                    or (
                        bound_object is None
                        and self.can_render_unbound_editable_layout_field(application_field)
                    )
                ) and field_type.editable_without_form_field,
                layout_config=config,
            )
        elif bound_object is not None:
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                value=get_object_field_value(obj=bound_object, application_field=application_field),
                can_edit=has_edit_permission and field_type.editable_without_form_field,
                layout_config=config,
            )
        elif (
            field_type.editable_without_form_field
            and self.can_render_unbound_editable_layout_field(application_field)
        ):
            field_context = build_crud_layout_field_context(
                application_field=application_field,
                value=self.get_unbound_layout_field_value(application_field),
                can_edit=True,
                layout_config=config,
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
                    config=item.config,
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
            "layout_object_content_type_id": self.get_layout_object_content_type_id(),
            "layout_object_id": self.get_layout_object_id(),
            "layout_object": layout_object,
            "layout_preference_object": self.get_layout_preference_object(),
            "layout": layout,
            "layout_mode": self.get_layout_mode(),
            "layout_available_items_url": self.get_layout_available_items_url(),
            "layout_save_url": self.get_layout_save_url(),
            "can_change_layout": self.can_change_layout(),
            "can_delete_layout_object": self.can_delete_layout_object(),
            "layout_render_item_url": self.get_layout_render_item_url(),
            "layout_is_create": self.is_create_layout(),
            "non_required_fields_visible_attr": self.get_non_required_fields_visible_attr(),
            "layout_container_extra_attrs": {
                "data-content-type-id": self.get_layout_content_type_id(),
                "data-non-required-fields-visible": self.get_non_required_fields_visible_attr(),
            },
        }
        bound_object = self.get_layout_bound_object()
        if bound_object is not None:
            context["layout_container_extra_attrs"]["data-object-id"] = bound_object.pk
        context.update(self.get_layout_context_extras(layout=layout_object, form=form))
        return context

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        explicit_layout_form = kwargs.pop("_layout_form", None)
        context = super().get_context_data(**kwargs)
        form = explicit_layout_form or self.get_layout_form(context=context)
        context["layout_has_form"] = form is not None
        layout_non_field_errors = list(form.non_field_errors()) if form is not None else []
        if form is not None:
            visible_field_names = self.get_layout_visible_field_names()
            hidden_field_errors = [
                f"{form.fields[field_name].label or field_name}: {error}"
                for field_name, errors in form.errors.items()
                if field_name != "__all__" and field_name not in visible_field_names and field_name in form.fields
                for error in errors
            ]
            if hidden_field_errors:
                layout_non_field_errors.extend(hidden_field_errors)
        context["layout_non_field_errors"] = layout_non_field_errors
        context.update(self.build_layout_context(form=form))
        return context
