from abc import ABC, abstractmethod
from functools import cached_property
from urllib.parse import urlencode
from django.utils.html import format_html
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django import forms
from django.db import models
from django.urls import reverse

from bloomerp.forms.model_form import (
    BloomerpModelForm,
    bloomerp_modelform_factory,
    get_model_form_application_fields,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.models import FieldLayout, LayoutItem
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.views.mixins.layout_form_mixin import LayoutFormMixin
from bloomerp.views.mixins.layout_mixin import ChangeContext, LayoutBinding


class ApplicationFieldLayoutFormMixin(LayoutFormMixin, ABC):
    """Render model fields without owning target-object persistence."""

    ts_container_component = "object-crud-view-container"
    ts_item_component = "detail-view-value"

    application_fields: models.QuerySet[ApplicationField] | None = None
    user: AbstractBloomerpUser | None = None
    apply_permissions: bool = True

    label_extractor_func = lambda self, item: self.render_label(item)
    content_extractor_func = lambda self, item: self.render_field(item)
    is_visible_extractor_func = lambda self, item: self.is_visible(item)
    not_visible_content_extractor_func = lambda self, item: (
        "<div class='text-gray-600 text-sm'>You don't have access to this field</div>"
    )
    def edit_url_extractor_func(self, item: LayoutItem) -> str | None:
        application_field = self.get_application_field(item)
        if not application_field.get_field_type().display_options:
            return None
        
        layout_object = self.get_layout_object()
        query = urlencode(
            {
                "layout_object_content_type_id": ContentType.objects.get_for_model(
                    layout_object
                ).pk,
                "layout_object_id": layout_object.pk,
            }
        )
        return reverse(
            "components_field_display_options",
            kwargs={"application_field_id": application_field.id},
        ) + f"?{query}"
    
    @abstractmethod
    def get_layout_binding(self) -> LayoutBinding:
        raise NotImplementedError

    @abstractmethod
    def get_view_permission_str(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_change_permission_str(self) -> str:
        raise NotImplementedError

    @cached_property
    def layout_binding(self) -> LayoutBinding:
        return self.get_layout_binding()

    @property
    def layout_content_type(self) -> ContentType:
        return self.layout_binding.target_content_type

    @property
    def layout_model(self) -> type[models.Model]:
        return self.layout_binding.target_model

    def get_layout_object(self) -> models.Model:
        return self.layout_binding.owner

    def get_layout(self) -> FieldLayout:
        """Exclude references to deleted fields from the rendered layout."""
        return self.valid_layout

    @cached_property
    def valid_layout(self) -> FieldLayout:
        """Build a request-local layout containing only existing model fields."""
        layout = self.layout_binding.layout.model_copy(deep=True)
        field_ids = {str(field.pk) for field in self.get_application_fields()}
        for row in layout.rows:
            row.items = [item for item in row.items if str(item.id) in field_ids]
        return layout

    def get_can_change(self) -> bool:
        return False

    def get_change_context(self) -> ChangeContext | None:
        return self.layout_binding.change_context

    def get_layout_container_extra_attrs(self) -> dict[str, object]:
        """Expose the saved behavior owner independently of layout editing controls."""
        attrs: dict[str, object] = {
            "data-target-content-type-id": self.layout_content_type.pk,
        }
        owner = self.get_layout_object()
        if isinstance(owner, (Form, UserObjectLayoutPreference)):
            attrs["data-behavior-url"] = reverse("components_form_behavior_execute")
            attrs["data-behavior-owner-key"] = (
                "form_id" if isinstance(owner, Form) else "preference_id"
            )
            attrs["data-behavior-owner-id"] = owner.pk
            instance = self.get_form_instance()
            if (
                instance is not None
                and not instance._state.adding
                and instance.pk is not None
            ):
                attrs["data-behavior-object-id"] = instance.pk
        return attrs

    def render_extra_attrs(self, item: LayoutItem) -> dict[str, object]:
        """Expose stable field metadata to layout-aware frontend components."""
        application_field = self.get_application_field(item)
        form_field = self.get_form().fields.get(application_field.field)
        is_json = isinstance(form_field, forms.JSONField) or (
            application_field.get_field_type().id == "OneToManyField"
        )
        return {
            **super().render_extra_attrs(item),
            "data-behavior-value-kind": "json" if is_json else "value",
            "data-application-field-id": application_field.pk,
            "data-field-name": application_field.field,
        }

    def get_user(self) -> AbstractBloomerpUser:
        if self.user is None:
            self.user = self.request.user
        return self.user

    @cached_property
    def permission_manager(self) -> UserPolicyManager:
        return UserPolicyManager(self.get_user())

    def get_permission_object(self) -> models.Model | None:
        """Return the persisted object that scopes field permissions, if any."""
        return None

    def get_accessible_application_fields(
        self,
        permission: str,
    ) -> models.QuerySet[ApplicationField]:
        """Resolve field access for either the model or the current object."""
        permission_object = self.get_permission_object()
        if permission_object is not None and permission_object.pk is not None:
            return self.permission_manager.get_accessible_fields_for_object(
                permission_object,
                permission,
            )
        return self.permission_manager.get_accessible_fields(
            self.layout_content_type,
            permission,
        )

    def get_accessible_application_field_ids(self, permission: str) -> set[int]:
        cache = getattr(self, "_accessible_application_field_ids", None)
        if cache is None:
            cache = {}
            self._accessible_application_field_ids = cache
        if permission not in cache:
            cache[permission] = set(
                self.get_accessible_application_fields(permission).values_list(
                    "pk",
                    flat=True,
                )
            )
        return cache[permission]

    def get_application_fields(self) -> models.QuerySet[ApplicationField]:
        """Load the model's fields referenced by the saved, unfiltered layout."""
        if self.application_fields is not None:
            return self.application_fields

        field_ids = [
            item.id
            for row in self.layout_binding.layout.rows
            for item in row.items
        ]
        self.application_fields = ApplicationField.objects.filter(
            content_type=self.layout_content_type,
            id__in=field_ids,
        ).select_related("content_type", "related_model")
        return self.application_fields

    def get_application_field(self, item: LayoutItem) -> ApplicationField:
        fields_by_id = getattr(self, "_application_fields_by_id", None)
        if fields_by_id is None:
            fields_by_id = {
                str(application_field.pk): application_field
                for application_field in self.get_application_fields()
            }
            self._application_fields_by_id = fields_by_id
        try:
            return fields_by_id[str(item.id)]
        except KeyError as exc:
            raise ValidationError(
                f"ApplicationField with id {item.id} does not exist for "
                f"{self.layout_model.__name__}"
            ) from exc

    def get_form_application_fields(self) -> models.QuerySet[ApplicationField]:
        cached_fields = getattr(self, "_form_application_fields", None)
        if cached_fields is not None:
            return cached_fields

        fields = self.get_application_fields()
        if self.apply_permissions:
            accessible_fields = self.get_accessible_application_fields(
                self.get_change_permission_str(),
            )
            fields = fields.filter(pk__in=accessible_fields.values("pk"))

        self._form_application_fields = get_model_form_application_fields(
            self.layout_model,
            fields,
        )
        return self._form_application_fields

    def resolve_form_key(self, item: LayoutItem) -> str:
        return self.get_application_field(item).field

    def get_layout_widget(self, item: LayoutItem, form_field):
        if not item.config:
            return super().get_layout_widget(item, form_field)
        return self.get_application_field(item).get_widget(
            layout_config=item.config,
        )

    def render_label(self, item: LayoutItem) -> str:
        label = item.config.get("label", self.get_application_field(item).title)
        
        if self.resolve_is_required(item):
            return format_html(
                "{} <span class='text-red-500'>*</span>",
                label,
            )
        
        return label

    def is_visible(self, item: LayoutItem) -> bool:
        if not self.apply_permissions:
            return True

        application_field = self.get_application_field(item)
        form_field_ids = getattr(self, "_form_application_field_ids", None)
        if form_field_ids is None:
            form_field_ids = {
                field.pk for field in self.get_form_application_fields()
            }
            self._form_application_field_ids = form_field_ids
        if application_field.pk not in form_field_ids:
            return False
        return application_field.pk in self.get_accessible_application_field_ids(
            self.get_view_permission_str()
        )

    def get_form_instance(self) -> models.Model | None:
        return None

    def get_form(self) -> BloomerpModelForm:
        cached_form = getattr(self, "_layout_form", None)
        if cached_form is not None:
            return cached_form

        application_fields = list(self.get_form_application_fields())
        form_class = bloomerp_modelform_factory(
            self.layout_model,
            [field.field for field in application_fields],
        )
        form = form_class(
            instance=self.get_form_instance(),
            initial=super().get_initial(),
        )
        self._layout_form = self.apply_layout_widget_config(form)
        return self._layout_form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["layout_object"] = self.get_layout_object()
        context["layout_object_id"] = self.get_layout_object().pk
        context["layout_object_content_type_id"] = (
            self.layout_binding.owner_content_type.pk
        )
        context["target_content_type"] = self.layout_content_type
        context["target_content_type_id"] = self.layout_content_type.pk
        context["layout_mode"] = self.layout_binding.layout_mode
        return context
