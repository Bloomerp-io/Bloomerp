"""Search and provision a phone number from a connection's object action."""

from typing import Any
import logging
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django_htmx.http import HttpResponseClientRedirect
from django.http import Http404
from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY
from bloomerp.communication.builtins.voip.definition import VoIPProviderDefinition
from bloomerp.router import router
from bloomerp.models.communication.voip import VoIPConnection
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.communication.builtins.voip.controller import adapter_for, VoIPController
from bloomerp.forms.communication.voip_number import (
    VoIPNumberSearchForm,
    VoIPNumberPurchaseForm,
)
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="phone-numbers/create/",
    route_type="detail",
    models=[VoIPConnection],
    url_name="create_voip_number",
    name="Create phone number",
)
class CreateVoIPNumberView(BaseBloomerpDetailView):
    """Keep availability reads separate from explicitly confirmed provisioning requests."""

    model = VoIPConnection
    template_name = "views/communication/create_voip_number.html"

    def has_permission(self) -> bool:
        """Require change access to the parent connection for both searches and purchases."""
        return (
            VoIPAccessManager(self.request.user)
            .get_connections()
            .filter(pk=self.kwargs["pk"])
            .exists()
        )

    def get_provider(self) -> VoIPProviderDefinition:
        """Require a provider that declares both number provisioning schemas."""
        provider = VOIP_PROVIDER_REGISTRY.get(self.object.provider)
        if (
            provider is None
            or provider.number_search_schema is None
            or provider.number_purchase_schema is None
        ):
            raise Http404
        return provider

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Search only after valid user input and sign each account-scoped offer."""
        context = super().get_context_data(**kwargs)
        provider = self.get_provider()
        context["provider"] = provider
        search = VoIPNumberSearchForm(
            self.request.GET or None, schema=provider.number_search_schema
        )
        context["search_form"] = search
        context.setdefault(
            "purchase_form",
            VoIPNumberPurchaseForm(schema=provider.number_purchase_schema),
        )
        context["offers"] = []
        if self.request.method == "GET" and search.is_bound and search.is_valid():
            if self.object.status != "active":
                search.add_error(
                    None, _("Synchronize this connection before searching for numbers.")
                )
            else:
                try:
                    offers = adapter_for(self.object).search_numbers(
                        search.options,
                    )
                    context["offers"] = [
                        {
                            "number": offer,
                            "token": signing.dumps(
                                {
                                    "connection": str(self.object.pk),
                                    "user": str(self.request.user.pk),
                                    "number": offer.number,
                                },
                                salt="voip-number-offer",
                            ),
                        }
                        for offer in offers
                    ]
                except provider.operation_errors:
                    search.add_error(
                        None,
                        _(
                            "Number search failed. Check the connection and provider availability."
                        ),
                    )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Provision only a recent offer signed for this connection and authenticated actor."""
        self.object = self.get_object()
        provider = self.get_provider()
        form = VoIPNumberPurchaseForm(
            request.POST, schema=provider.number_purchase_schema
        )
        if form.is_valid():
            try:
                offer = signing.loads(
                    form.cleaned_data["selection"],
                    salt="voip-number-offer",
                    max_age=900,
                )
                if offer["connection"] != str(self.object.pk) or offer["user"] != str(
                    request.user.pk
                ):
                    raise signing.BadSignature
                line = VoIPController(request.user).provision_number(
                    self.object.pk,
                    offer["number"],
                    form.cleaned_data["name"],
                    form.options,
                )
            except (signing.BadSignature, KeyError):
                form.add_error(
                    None,
                    _(
                        "This selection has expired or is invalid. Search for the number again."
                    ),
                )
            except (*provider.operation_errors, ValidationError) as error:
                error_code = getattr(error, "code", None)
                safe_code = error_code if type(error_code) is int else None
                logging.getLogger(__name__).warning(
                    "Number provisioning failed: provider=%s connection=%s error_type=%s code=%s",
                    self.object.provider,
                    self.object.pk,
                    type(error).__name__,
                    safe_code,
                )
                message = _(
                    "Provisioning could not be confirmed. Synchronize before retrying; check number availability and the provider requirements."
                )
                if safe_code is not None:
                    message += " " + _("Provider error code: %(code)s.") % {
                        "code": safe_code
                    }
                form.add_error(None, message)
            else:
                url = line.get_absolute_url()
                return (
                    HttpResponseClientRedirect(url)
                    if getattr(request, "htmx", False)
                    else redirect(url)
                )
        return self.render_to_response(self.get_context_data(purchase_form=form))
