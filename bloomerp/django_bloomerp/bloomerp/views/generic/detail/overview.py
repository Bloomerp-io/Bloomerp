from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django_htmx.http import trigger_client_event

from bloomerp.forms.model_form import BloomerpModelForm
from bloomerp.models.definition import ObjectActionDefinition
from bloomerp.permissions.manager import create_permission_str
from bloomerp.router import router
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.layout_model_form_mixin import LayoutModelFormMixin


@router.register(
    path="/",
    name="Details",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailOverviewView(LayoutModelFormMixin, BaseBloomerpDetailView):
    layout_mode = "detail"

    def has_permission(self):
        self.object = self.get_object()
        return self.permission_manager.has_access_to_object(
            self.object,
            self.get_view_permission_str()
        )
    
    def get_view_permission_str(self):
        return create_permission_str(self.model, "view")

    def get_change_permission_str(self):
        return create_permission_str(self.model, "change")

    def get_object_actions(self) -> list[ObjectActionDefinition]:
        """Limit the visible actions to the token's configured allowlist when supplied."""
        actions = super().get_object_actions()
        token = self.detail_view_token
        if token is None or token.object_actions is None:
            return actions
        return [action for action in actions if action.id in token.object_actions]

    def get_success_response(self, form: BloomerpModelForm) -> HttpResponse:
        """Render the saved details and notify DataViews after an embedded edit."""
        self.add_message(f"Object '{self.object}' updated", "success")
        if getattr(self.request, "htmx", False):
            context = self.get_context_data()
            response = self.render_to_response(context)
            if context["embedded_detail_view"]:
                trigger_client_event(
                    response, "bloomerp:dataview-refresh",
                    {"contentTypeId": self.layout_content_type.pk}, after="swap",
                )
            return response
        url = reverse(get_detail_view_url(self.model), kwargs={"pk": self.object.pk})
        return redirect(url)
