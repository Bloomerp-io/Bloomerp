"""Reconfigure carrier credentials through an authorized model detail view."""

from typing import Any
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django_htmx.http import HttpResponseClientRedirect
from bloomerp.router import router
from bloomerp.models.communication.voip import VoIPConnection
from bloomerp.forms.communication.im_connection import IMConnectionForm
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.communication.builtins.voip.controller import callback_url
from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="reconfigure/",
    route_type="detail",
    models=[VoIPConnection],
    url_name="reconfigure_voip_connection",
    name="Reconfigure connection",
)
class ReconfigureVoIPConnectionView(BaseBloomerpDetailView):
    """Preserve account identity and blank credentials while updating provider settings."""

    model = VoIPConnection
    template_name = "views/communication/reconfigure_voip_connection.html"

    def has_permission(self) -> bool:
        """Require current connection change permission, independent of ownership."""
        from bloomerp.permissions.manager import UserPolicyManager

        connection = self.get_object()
        if not UserPolicyManager(self.request.user).has_access_to_object(
            connection, "change", fields=["name", "settings", "credentials"]
        ):
            return False
        return (
            VoIPAccessManager(self.request.user)
            .get_connections()
            .filter(pk=self.kwargs["pk"])
            .exists()
        )

    def build_form(self, data: Any = None) -> IMConnectionForm:
        """Never put stored credentials into form initial values or rendered HTML."""
        initial = {**self.object.settings, "name": self.object.name}
        form = IMConnectionForm(
            data=data,
            provider=VOIP_PROVIDER_REGISTRY.get(self.object.provider),
            initial=initial,
            stored_credentials=self.object.get_credentials()
            if data is not None
            else {},
        )
        if form.provider.account_id_field:
            name = form.provider.account_id_field
            form.fields[name].disabled = True
            form.initial[name] = self.object.external_account_id
        for name in form.provider.immutable_config_fields:
            form.fields[name].disabled = True
            if name != form.provider.account_id_field:
                form.initial[name] = self.object.settings.get(name)
        return form

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Show editable provider fields and callback addresses beside the form."""
        context = super().get_context_data(**kwargs)
        context.setdefault("form", self.build_form())
        provider = VOIP_PROVIDER_REGISTRY.get(self.object.provider)
        context["callback_help"] = provider.callback_help
        context["callback_urls"] = [
            {"label": label, "url": callback_url(self.object, kind)}
            for kind, label in provider.callback_labels.items()
        ]
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Persist encrypted replacements atomically and require a fresh validation."""
        with transaction.atomic():
            self.object = VoIPConnection.objects.select_for_update().get(
                pk=self.kwargs["pk"]
            )
            form = self.build_form(request.POST)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form=form))
            settings, credentials = form.split_configuration()
            self.object.name = form.configuration.name
            self.object.settings = settings
            self.object.set_credentials(credentials)
            self.object.status = "draft"
            self.object.validated_at = None
            self.object.updated_by = request.user
            self.object.save()
        url = self.object.get_absolute_url()
        return (
            HttpResponseClientRedirect(url)
            if getattr(request, "htmx", False)
            else redirect(url)
        )
