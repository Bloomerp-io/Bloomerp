"""Model object actions for permission-scoped carrier administration."""

from __future__ import annotations
import json
from typing import TYPE_CHECKING
from uuid import UUID
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import RegexValidator
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django_htmx.http import HttpResponseClientRedirect
from bloomerp.utils.async_utils import run_async_or_sync
from bloomerp.utils.requests import render_blank_form, render_message
from bloomerp.form_fields.phone_number_field import PhoneNumberFormField
from bloomerp.widgets.phone_number_widget import PhoneNumberWidget

if TYPE_CHECKING:
    from bloomerp.communication.builtins.instant_messaging.definition import (
        IMCreationAction,
        IMProviderDefinition,
    )
    from bloomerp.models.definition import DataviewActionContext
    from bloomerp.models.communication.voip import VoIPConnection


def can_change_connection(request: HttpRequest, connection: VoIPConnection) -> bool:
    """Check the same current global and object change grants used by administration views."""
    from .access import VoIPAccessManager

    return (
        VoIPAccessManager(request.user)
        .get_connections()
        .filter(pk=connection.pk)
        .exists()
    )


def synchronize_connection_job(connection_id: UUID, user_id: int) -> str:
    """Recheck actor permissions inside the worker before synchronizing a carrier account."""
    from .controller import VoIPController

    user = get_user_model().objects.get(pk=user_id)
    connection = VoIPController(user).synchronize(connection_id)
    return str(connection.pk)


def synchronize_numbers(
    request: HttpRequest, connection: VoIPConnection
) -> HttpResponse:
    """Queue carrier synchronization when a worker is available, otherwise execute it inline."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not can_change_connection(request, connection):
        return HttpResponseForbidden()
    try:
        queued, result = run_async_or_sync(
            synchronize_connection_job, connection.pk, request.user.pk
        )
    except Exception:
        return render_message(
            request,
            _("Synchronization failed. Check the connection configuration."),
            "error",
        )
    return render_message(
        request,
        _("Phone number synchronization queued.")
        if queued
        else _("Phone numbers synchronized."),
        "success",
    )


def open_number_creation(
    request: HttpRequest, connection: VoIPConnection
) -> HttpResponse:
    """Open the authorized provisioning form from the connection's object actions."""
    return open_connection_view(request, connection, "create_voip_number")


def open_reconfiguration(
    request: HttpRequest, connection: VoIPConnection
) -> HttpResponse:
    """Open provider settings without exposing stored credentials in generic layouts."""
    return open_connection_view(request, connection, "reconfigure_voip_connection")


def open_connection_view(
    request: HttpRequest, connection: VoIPConnection, view_name: str
) -> HttpResponse:
    """Resolve an object route after rechecking its server-side authorization."""
    if not can_change_connection(request, connection):
        return HttpResponseForbidden()
    url = reverse(f"voip_connections_detail_{view_name}", kwargs={"pk": connection.pk})
    return (
        HttpResponseClientRedirect(url)
        if getattr(request, "htmx", False)
        else redirect(url)
    )


def can_create_connection(context: DataviewActionContext) -> bool:
    """Show the provider wizard link only to users with model add permission."""
    from bloomerp.permissions.manager import UserPolicyManager

    return UserPolicyManager(context.request.user).has_global_permission(
        context.model, "add"
    )


def can_dial(request: HttpRequest) -> bool:
    """Allow manual phone chats for actors with an available telephone line."""
    from .access import VoIPAccessManager

    return VoIPAccessManager(request.user).get_numbers().exists()


def dial(
    request: HttpRequest,
    provider_definition: IMProviderDefinition,
    action: IMCreationAction,
) -> HttpResponse:
    """Collect a recipient and authorized business line, then open their phone chat."""
    from .access import VoIPAccessManager

    from bloomerp.communication.builtins.instant_messaging.builtins.phone import (
        start_phone_address,
    )
    from bloomerp.components.communication.instant_messaging.conversation import (
        render_conversation,
    )

    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    if not can_dial(request):
        raise PermissionDenied
    numbers = (
        VoIPAccessManager(request.user)
        .get_numbers()
        .select_related("connection")
        .order_by("number")
    )
    form = forms.Form(request.POST if request.method == "POST" else None)
    form.fields["phone_number"] = PhoneNumberFormField(
        label=_("Phone number"),
        validators=[
            RegexValidator(
                r"^\+[1-9][0-9]{3,14}$",
                _("Enter an international phone number including the country code."),
            )
        ],
        widget=PhoneNumberWidget(
            attrs={
                "class" : "input w-full"
            }
        )
    )
    form.fields["number_id"] = forms.ModelChoiceField(
        label=_("Business number"), queryset=numbers,
    )
    if numbers.count() == 1:
        form.initial["number_id"] = numbers.first().pk
    if request.method == "POST" and form.is_valid():
        try:
            chat = start_phone_address(
                request.user,
                form.cleaned_data["number_id"].pk,
                form.cleaned_data["phone_number"],
            )
        except (ValueError, ValidationError) as error:
            form.add_error(None, error)
        else:
            response = render_conversation(request, chat.pk)
            response["HX-Retarget"] = "#im-conversation-host"
            response["HX-Reswap"] = "innerHTML"
            response["HX-Trigger"] = json.dumps(
                {
                    "im:conversation-opened": {
                        "id": str(chat.pk),
                        "target": "[bloomerp-component='bloomerp:messaging-panel']",
                    }
                }
            )
            response["Cache-Control"] = "private, no-store"
            return response
    response = render_blank_form(
        request,
        form,
        reverse("components_im_create_group"),
        hidden_args={"provider": provider_definition.key, "action": action.key},
        submit_label=_("Start chat"),
        form_args={"hx-disabled-elt": "find button"},
    )
    response["Cache-Control"] = "private, no-store"
    return response
