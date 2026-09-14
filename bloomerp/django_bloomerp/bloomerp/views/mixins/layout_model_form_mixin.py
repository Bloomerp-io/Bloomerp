from abc import ABC, abstractmethod
from typing import Type

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from regex import B

from bloomerp.forms.model_form import (
    BloomerpModelForm,
    bloomerp_modelform_factory,
    get_model_form_application_fields,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.mixins.application_field_layout_form_mixin import (
    ApplicationFieldLayoutFormMixin,
)
from bloomerp.views.mixins.layout_mixin import LayoutBinding


class LayoutModelFormMixin(ApplicationFieldLayoutFormMixin, ABC):
    """Render and process a model-backed layout form."""

    template_name = "mixins/bloomerp_layout_form_mixin.html"
    ts_container_component = "object-crud-view-container"
    ts_item_component = "detail-view-value"

    model: Type[models.Model]

    @abstractmethod
    def get_view_permission_str(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_change_permission_str(self) -> str:
        raise NotImplementedError

    def get_layout_binding(self) -> LayoutBinding:
        target_content_type = ContentType.objects.get_for_model(self.model)
        owner = PreferenceManager(self.get_user()).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": target_content_type.pk},
        )
        return LayoutBinding(
            owner=owner,
            target_content_type=target_content_type,
            layout_mode=self.layout_mode,
        )

    def get_can_change(self):
        return PreferenceManager(self.get_user()).can_manage(self.get_layout_object())

    def get_layout_container_extra_attrs(self) -> dict[str, object]:
        attrs = super().get_layout_container_extra_attrs()
        if self.layout_mode == "detail":
            attrs["data-object-id"] = self.get_form_instance().pk
        return attrs

    def is_create_layout(self) -> bool:
        return self.layout_mode == "create"

    def get_permission_object(self) -> models.Model | None:
        if self.is_create_layout():
            return None
        return self.get_form_instance()

    def get_form_hx_target(self) -> str:
        if self.is_create_layout():
            return "#main-content"

        htmx_target = getattr(getattr(self.request, "htmx", None), "target", None)
        if htmx_target == "data-table-detail-pane":
            return "#data-table-detail-pane"

        return "#detail-view-content"

    def get_form_hx_push_url(self) -> bool:
        return self.is_create_layout()

    def get_full_form_url(self) -> str | None:
        return None

    def get_hidden_initial_fields(self) -> list[tuple[str, str]]:
        if not self.is_create_layout():
            return []

        form = self.get_form()
        layout_field_names = {
            self.resolve_form_key(item)
            for row in self.get_layout().rows
            for item in row.items
        }
        one_to_many_columns: dict[str, set[str]] = {}
        for field_name in layout_field_names:
            form_field = form.fields.get(field_name)
            get_columns = (
                getattr(form_field.widget, "get_columns", None)
                if form_field
                else None
            )
            if not callable(get_columns):
                continue
            one_to_many_columns[field_name] = {
                column.field for column in get_columns()
            }

        submitted_data = (
            self.request.POST
            if self.request.method.upper() == "POST"
            else self.request.GET
        )
        return [
            (field_name, value)
            for field_name, value in submitted_data.items()
            if not self._is_rendered_initial_field(
                field_name,
                layout_field_names,
                one_to_many_columns,
            )
        ]

    @staticmethod
    def _is_rendered_initial_field(
        field_name: str,
        layout_field_names: set[str],
        one_to_many_columns: dict[str, set[str]],
    ) -> bool:
        """Return whether a query value already has a rendered form control."""
        if field_name in layout_field_names:
            return True

        for parent_name, column_names in one_to_many_columns.items():
            prefix = f"{parent_name}__"
            if not field_name.startswith(prefix):
                continue
            nested_parts = field_name[len(prefix):].split("__", 1)
            return len(nested_parts) == 2 and nested_parts[1] in column_names

        return False

    def get_form_application_fields(self) -> models.QuerySet[ApplicationField]:
        """Return the application fields represented by the model form."""
        cached_fields = getattr(self, "_form_application_fields", None)
        if cached_fields is not None:
            return cached_fields
        if self.is_create_layout():
            fields = ApplicationField.get_for_model(self.model)
            if self.apply_permissions:
                accessible_fields = self.get_accessible_application_fields(
                    self.get_change_permission_str(),
                )
                fields = fields.filter(pk__in=accessible_fields.values("pk"))
            self._form_application_fields = get_model_form_application_fields(
                self.model,
                fields,
            )
            return self._form_application_fields
        if not self.is_create_layout():
            fields = self.get_application_fields()
            if self.apply_permissions:
                accessible_fields = self.get_accessible_application_fields(
                    self.get_view_permission_str(),
                )
                fields = fields.filter(pk__in=accessible_fields.values("pk"))
            self._form_application_fields = get_model_form_application_fields(
                self.model,
                fields,
            )
            return self._form_application_fields
        return super().get_form_application_fields()

    def get_create_access_errors(self) -> list[str]:
        if not self.is_create_layout():
            return []

        permitted_names = set(
            self.get_form_application_fields().values_list("field", flat=True)
        )
        missing_required_fields = []
        for model_field in self.model._meta.concrete_fields:
            if (
                getattr(model_field, "auto_created", False)
                or not getattr(model_field, "editable", True)
                or getattr(model_field, "null", False)
                or getattr(model_field, "blank", False)
                or getattr(model_field, "auto_now", False)
                or getattr(model_field, "auto_now_add", False)
                or model_field.has_default()
            ):
                continue
            application_field = ApplicationField.get_by_field(
                self.model,
                model_field.name,
            )
            if application_field is not None and model_field.name not in permitted_names:
                missing_required_fields.append(application_field)

        errors = []
        if missing_required_fields:
            field_titles = ", ".join(
                sorted(field.title for field in missing_required_fields)
            )
            errors.append(
                "You do not have permission to create this object because you do "
                f"not have access to the required fields: {field_titles}."
            )

        manager = UserPolicyManager(self.get_user())
        if not manager.has_row_level_access(
            self.model,
            self.get_change_permission_str(),
        ):
            errors.append(
                "You do not have permission to create this object because no "
                "create row policy applies to you."
            )
        return errors

    def get_form_instance(self) -> models.Model:
        if getattr(self, "object", None) is None:
            self.object = self.model() if self.is_create_layout() else self.get_object()
        return self.object

    def get_form(self) -> BloomerpModelForm:
        cached_form = getattr(self, "_layout_form", None)
        if cached_form is not None:
            return cached_form

        application_fields = list(self.get_form_application_fields())
        form_class = bloomerp_modelform_factory(
            self.model,
            [field.field for field in application_fields],
        )
        is_post = (
            self.request.method.upper() == "POST"
            and not getattr(self, "_render_saved_form", False)
        )
        instance = self.get_form_instance()
        initial = super().get_initial()
        if self.is_create_layout():
            initial = form_class.prepare_initial_data(
                initial,
                self.request.GET,
                application_fields,
            )
        form_data = None
        if is_post:
            form_data = form_class.prepare_bound_data(
                self.request.POST,
                self.request.FILES,
                instance,
                partial=not self.is_create_layout(),
            )
        form = form_class(
            data=form_data,
            files=self.request.FILES if is_post else None,
            instance=instance,
            initial=initial,
        )

        if self.apply_permissions:
            change_permission = self.get_change_permission_str()
            changeable_field_ids = self.get_accessible_application_field_ids(
                change_permission
            )
            fields_by_name = {field.field: field for field in application_fields}
            for field_name, form_field in form.fields.items():
                application_field = fields_by_name.get(field_name)
                if application_field is not None:
                    form_field.disabled = (
                        form_field.disabled
                        or application_field.pk not in changeable_field_ids
                    )
        self.apply_layout_widget_config(form)
        self._layout_form = form
        return form

    def get_submitted_application_field_names(self) -> set[str]:
        """Return parent layout field names represented in POST or FILES."""
        submitted_names: set[str] = set()
        for submitted_data in (self.request.POST, self.request.FILES):
            for key in submitted_data.keys():
                if key == "csrfmiddlewaretoken":
                    continue
                submitted_names.add(key.split("__", 1)[0])
        return submitted_names

    def get_denied_submitted_fields(self) -> list[str]:
        change_permission = self.get_change_permission_str()
        changeable_field_ids = self.get_accessible_application_field_ids(
            change_permission
        )
        application_fields = {
            field.field: field
            for field in ApplicationField.get_for_model(self.model).filter(
                field__in=self.get_submitted_application_field_names(),
            )
        }
        return sorted(
            field_name
            for field_name, application_field in application_fields.items()
            if application_field.pk not in changeable_field_ids
        )

    def validate_form_permissions(self, form: BloomerpModelForm) -> bool:
        """Validates the permissions on a form

        Args:
            form (BloomerpModelForm): the model form

        Returns:
            bool: _description_
        """
        if not self.apply_permissions:
            return True

        for error in self.get_create_access_errors():
            form.add_error(None, error)

        denied_fields = self.get_denied_submitted_fields()
        if denied_fields:
            form.add_error(
                None,
                f"Permission denied for fields: {', '.join(denied_fields)}",
            )

        manager = UserPolicyManager(self.get_user())
        instance = self.get_form_instance()
        change_permission = self.get_change_permission_str()

        # Check row level access
        if manager.has_row_level_access(self.model, change_permission):
            if not manager.candidate_matches_row_policies(
                instance,
                change_permission,
            ):
                form.add_error(
                    None,
                    "You do not have permission to create an object with these values.",
                )
        
        # Check object level access
        elif not manager.has_access_to_object(instance, change_permission):
            form.add_error(None, "You do not have permission to edit this object.")


        # Check one-to-many field access
        for _, o2m_data in form.get_cleaned_o2m_data().items():
            for instance in o2m_data:
                if instance.changed or instance.created:
                    permission = BloomerpPermission.CHANGE if instance.changed else BloomerpPermission.ADD
                    
                    if not manager.candidate_matches_row_policies(
                        candidate=instance.object,
                        permissions=permission,
                    ):
                        form.add_error(
                            None,
                            f"You do not have permission to {permission.value.name.lower()} '{instance.object}'.",
                        )
                if instance.deleted:
                    if not manager.has_access_to_object(
                        instance.object,
                        BloomerpPermission.DELETE,
                    ):
                        form.add_error(
                            None,
                            f"You do not have permission to {BloomerpPermission.DELETE.value.name.lower()} '{instance.object}'.",
                        )
        
        return not form.errors

    def form_valid(self, form: BloomerpModelForm):
        try:
            self.object = form.save()
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        self.object.refresh_from_db()
        self._layout_form = None
        self._render_saved_form = True
        return self.get_success_response(form)

    def form_invalid(self, form: BloomerpModelForm):
        self._layout_form = form
        return self.render_to_response(self.get_context_data())

    def get_success_response(self, form: BloomerpModelForm):
        return super().form_valid(form)

    def post(self, request, *args, **kwargs):
        self.object = self.get_form_instance()
        form = self.get_form()
        if form.is_valid() and self.validate_form_permissions(form):
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["layout_preference_object"] = self.get_layout_object()
        context["content_type_id"] = self.layout_content_type.pk
        context["model_name"] = self.model._meta.verbose_name
        context["model_key"] = self.model._meta.model_name
        if self.request.method.upper() != "POST":
            context["layout_non_field_errors"] = [
                *context.get("layout_non_field_errors", []),
                *self.get_create_access_errors(),
            ]
        context["layout_is_create"] = self.is_create_layout()
        context["layout_mode"] = self.layout_mode
        context["form_hx_target"] = self.get_form_hx_target()
        context["form_hx_push_url"] = self.get_form_hx_push_url()
        context["full_form_url"] = self.get_full_form_url()
        context["hidden_initial_fields"] = self.get_hidden_initial_fields()
        return context
