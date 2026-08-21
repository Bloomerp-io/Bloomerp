from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic.edit import CreateView

from bloomerp.forms.model_form import BloomerpModelForm
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.files import File
from bloomerp.models.workspaces import SqlQuery, Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.permission_services import create_permission_str
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_model_form_mixin import LayoutModelFormMixin


User = get_user_model()


def _redirect_url(model: type[models.Model], obj: models.Model) -> str | None:
    config = getattr(model, "bloomerp_config", None)
    if isinstance(config, BloomerpModelConfig) and config.create_redirect_url_func:
        return config.create_redirect_url_func(obj)
    if hasattr(obj, "get_absolute_url"):
        return obj.get_absolute_url()
    return None


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    exclude_models=[File, Tile, SqlQuery, User, Workspace],
)
class BloomerpCreateView(BaseBloomerpView, LayoutModelFormMixin, CreateView):
    layout_mode = "create"

    def has_permission(self):
        return UserPolicyManager(self.request.user).has_global_permission(
            self.model,
            self.get_change_permission_str(),
        )
    
    def get_view_permission_str(self):
        return create_permission_str(self.model, "add")

    def get_change_permission_str(self):
        return create_permission_str(self.model, "add")

    def get_success_url(self):
        if getattr(self, "object", None) is None:
            return self.request.path
        return _redirect_url(self.model, self.object) or self.request.path

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

    def get_success_response(self, form: BloomerpModelForm):
        object_url = _redirect_url(self.model, self.object)
        if object_url:
            message = f"Object successfully created: <a href='{object_url}'>{self.object}</a>"
        else:
            message = f"Object successfully created: {self.object}"
        self.add_message(message, "success")

        save_and_create_new_url = self.get_save_and_create_new_url()
        if save_and_create_new_url:
            return redirect(save_and_create_new_url)
        return redirect(self.get_success_url())
