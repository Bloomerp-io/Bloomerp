"""Model object actions for permission-scoped carrier administration."""

from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID
from django.contrib.auth import get_user_model
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
from bloomerp.utils.requests import render_message

if TYPE_CHECKING:
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
