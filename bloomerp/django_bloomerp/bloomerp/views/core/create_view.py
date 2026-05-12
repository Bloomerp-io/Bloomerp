from __future__ import annotations

from functools import cached_property

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic.edit import CreateView

from bloomerp.models import UserCreateViewPreference
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files import File
from bloomerp.models.workspaces import SqlQuery, Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.create_view_services import (
    get_create_access_state,
    get_disallowed_submitted_fields,
)
from bloomerp.services.one_to_many_field_services import save_submitted_one_to_many_fields
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.message_mixin import MessageMixin
from bloomerp.views.mixins.model_form_view_mixin import BloomerpModelFormViewMixin
from bloomerp.views.mixins.layout_form_mixin import BloomerpLayoutFormMixin


User = get_user_model()


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    exclude_models=[File, Tile, SqlQuery, User, Workspace, DocumentTemplate],
)
class BloomerpCreateView(
    BaseBloomerpView,
    BloomerpModelFormViewMixin,
    BloomerpLayoutFormMixin,
    MessageMixin,
    CreateView,
):
    template_name = "mixins/bloomerp_layout_form_mixin.html"
    fields = None
    exclude = []
    layout_mode = "create"

    @cached_property
    def layout_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(self.model)

    def has_permission(self):
        manager = UserPermissionManager(self.request.user)
        return manager.has_global_permission(
            self.model,
            create_permission_str(self.model, "add"),
        )

    def get_layout_content_type(self) -> ContentType:
        return self.layout_content_type

    def get_layout_object(self):
        return self.get_layout_preference_object().field_layout_obj

    def get_layout_preference_object(self):
        return UserCreateViewPreference.get_or_create_for_user(
            self.request.user,
            self.model,
        )

    def get_layout_editable_field_names(self) -> list[str]:
        return list(self.create_access_state.addable_fields.values_list("field", flat=True))

    def get_layout_available_items_url(self) -> str:
        return ""

    def get_layout_save_url(self) -> str:
        return ""

    def can_change_layout(self) -> bool:
        return True

    def get_non_required_fields_visible_default(self) -> bool:
        return True

    @cached_property
    def create_access_state(self):
        return get_create_access_state(
            content_type=self.get_layout_content_type(),
            user=self.request.user,
        )

    def get_initial(self):
        initial = super().get_initial()
        for key, value in self.request.GET.items():
            if key in self.get_layout_editable_field_names():
                initial[key] = value
        return initial

    def get_form_class(self):
        return self.get_form_class_for_fields(self.get_layout_editable_field_names())

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        allowed_fields = set(self.get_layout_editable_field_names())
        for field_name in list(form.fields.keys()):
            if field_name not in allowed_fields:
                form.fields.pop(field_name)
        return form

    def get_success_url(self):
        if getattr(self, "object", None) is None:
            return self.request.path
        return reverse(get_detail_view_url(self.model), kwargs={"pk": self.object.pk})

    def get_save_and_create_new_url(self) -> str | None:
        next_url = self.request.POST.get("next")
        if not next_url:
            return None

        if url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url

        return self.request.path

    def get_form_hx_target(self) -> str:
        return "#main-content"

    def get_form_hx_push_url(self) -> bool:
        return True

    def get_full_form_url(self) -> str | None:
        return None

    def get_hidden_initial_fields(self) -> list[tuple[str, str]]:
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_hx_target"] = self.get_form_hx_target()
        context["form_hx_push_url"] = self.get_form_hx_push_url()
        context["full_form_url"] = self.get_full_form_url()
        context["hidden_initial_fields"] = self.get_hidden_initial_fields()
        context["create_blocked"] = self.create_access_state.is_blocked
        context["create_blocked_message"] = self.create_access_state.blocked_message
        context["model_name"] = self.model._meta.verbose_name
        return context

    def _add_form_error(self, form, message: str):
        form.add_error(None, message)
        return self.form_invalid(form)

    def post(self, request, *args, **kwargs):
        if self.create_access_state.is_blocked:
            raise PermissionDenied(self.create_access_state.blocked_message or "Permission denied")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        allowed_field_names = set(self.get_layout_editable_field_names())
        denied_fields = get_disallowed_submitted_fields(
            model=self.model,
            submitted_data=self.request.POST,
            allowed_field_names=allowed_field_names,
        )
        if denied_fields:
            return self._add_form_error(form, f"Permission denied for fields: {', '.join(denied_fields)}")

        if not self.create_access_state.has_add_row_rules:
            return self._add_form_error(
                form,
                "You do not have permission to create this object because no create row policy applies to you.",
            )

        permission_manager = UserPermissionManager(self.request.user)
        if not permission_manager.candidate_matches_row_policies(
            self.model,
            create_permission_str(self.model, "add"),
            form.cleaned_data,
        ):
            return self._add_form_error(
                form,
                "You do not have permission to create an object with these values.",
            )

        try:
            with transaction.atomic():
                self.object = form.save(commit=False)
                if hasattr(self.object, "updated_by"):
                    self.object.updated_by = self.request.user
                if hasattr(self.object, "created_by") and not self.object.created_by:
                    self.object.created_by = self.request.user
                self.object.save()
                if hasattr(form, "save_m2m"):
                    form.save_m2m()
                if hasattr(self.object, "save_file_fields"):
                    self.object.save_file_fields()
                save_submitted_one_to_many_fields(
                    parent_object=self.object,
                    layout=self.get_layout_preference_object().field_layout_obj,
                    submitted_data=self.request.POST,
                    user=self.request.user,
                )
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
            return self.form_invalid(form)

        save_and_create_new_url = self.get_save_and_create_new_url()
        
        # Construct success message
        success_message = "Object successfully created: "
        if hasattr(self.object, 'get_absolute_url'):
            url = self.object.get_absolute_url()
        else:
            url = None
        
        if url:
            success_message += f" <a hx-get='{url}' hx-target='#main-content' hx-push-url='true'><b>{self.object}</b></a>"
        
        
        self.add_message(
            f"Object successfully created: <a href='{url}'>{self.object}</a>",
            "success"
        )
        
        if save_and_create_new_url:
            return redirect(save_and_create_new_url)
        
        return redirect(self.get_success_url())

