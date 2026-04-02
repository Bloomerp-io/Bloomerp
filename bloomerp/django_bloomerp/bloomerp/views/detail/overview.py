from __future__ import annotations

from functools import cached_property
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect

from bloomerp.models import ApplicationField
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.create_view_services import AUTO_MANAGED_FIELD_NAMES, get_disallowed_submitted_fields
from bloomerp.services.detail_view_services import get_default_layout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView
from bloomerp.views.view_mixins.form import BloomerpLayoutFormMixin


@router.register(
    path="/",
    name="Details",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailOverviewView(BloomerpLayoutFormMixin, BloomerpBaseDetailView):
    template_name = "mixins/bloomerp_layout_form_mixin.html"
    settings = None
    layout_mode = "detail"

    def get_layout_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(self.model)

    def get_layout_object(self):
        return self.layout_preference.field_layout_obj

    @cached_property
    def layout_preference(self) -> UserDetailViewPreference:
        content_type = self.get_layout_content_type()
        preference = UserDetailViewPreference.get_or_create_for_user(self.request.user, content_type)
        if not any(row.items for row in preference.field_layout_obj.rows):
            preference.field_layout = get_default_layout(
                content_type=content_type,
                user=self.request.user,
            ).model_dump()
            preference.save(update_fields=["field_layout"])
        return preference

    def get_layout_available_items_url(self) -> str:
        return "/components/workspaces/detail_layout_available_fields/?content_type_id=%s" % self.get_layout_content_type_id()

    def get_layout_save_url(self) -> str:
        return "/components/workspaces/detail_layout_preference/"

    def can_change_layout(self) -> bool:
        return True

    def get_layout_editable_field_names(self) -> list[str]:
        permission_manager = UserPermissionManager(self.request.user)
        content_type = self.get_layout_content_type()
        editable_fields = permission_manager.get_accessible_fields(
            content_type,
            create_permission_str(self.model, "change"),
        ).order_by("field")

        allowed_field_names: list[str] = []
        for application_field in editable_fields:
            if application_field.field in AUTO_MANAGED_FIELD_NAMES:
                continue
            field_type = application_field.get_field_type_enum().value
            if not field_type.allow_in_model:
                continue
            try:
                model_field = application_field._get_model_field()
            except Exception:
                continue
            if not getattr(model_field, "editable", True):
                continue
            if not getattr(model_field, "concrete", True):
                continue
            try:
                form_field = application_field.get_form_field()
            except Exception:
                continue
            if form_field is None:
                continue
            allowed_field_names.append(application_field.field)
        return allowed_field_names

    def _build_update_candidate_data(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        candidate_data: dict[str, Any] = {}
        for model_field in self.model._meta.concrete_fields:
            if getattr(model_field, "auto_created", False):
                continue
            candidate_data[model_field.name] = getattr(self.object, model_field.name, None)
        candidate_data.update(cleaned_data)
        return candidate_data

    def form_valid(self, form):
        allowed_field_names = set(self.get_layout_editable_field_names())
        denied_fields = get_disallowed_submitted_fields(
            model=self.model,
            submitted_data=self.request.POST,
            allowed_field_names=allowed_field_names,
        )
        if denied_fields:
            form.add_error(None, f"Permission denied for fields: {', '.join(denied_fields)}")
            return self.form_invalid(form)

        permission_manager = UserPermissionManager(self.request.user)
        change_permission = create_permission_str(self.model, "change")
        if not permission_manager.has_access_to_object(self.object, change_permission):
            form.add_error(None, "You do not have permission to edit this object.")
            return self.form_invalid(form)

        if not permission_manager.candidate_matches_row_policies(
            self.model,
            change_permission,
            self._build_update_candidate_data(form.cleaned_data),
        ):
            form.add_error(None, "You do not have permission to update this object with these values.")
            return self.form_invalid(form)

        self.object = form.save()
        if getattr(self.request, "htmx", False):
            return self.render_to_response(self.get_context_data())
        return redirect(get_detail_view_url(self.model), pk=self.object.pk)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(_layout_form=form))

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.build_layout_form()
        if form is None:
            return redirect(get_detail_view_url(self.model), pk=self.object.pk)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_context_data(self, **kwargs: Any) -> dict:
        self.object = self.get_object()
        context = super().get_context_data(**kwargs)
        context["content_type_id"] = self.get_layout_content_type_id()
        return context
