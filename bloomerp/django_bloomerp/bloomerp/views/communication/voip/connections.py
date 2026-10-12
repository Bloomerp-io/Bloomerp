"""Manage carrier accounts through the same owner-scoped access boundary as setup."""

from typing import Any
from django.contrib.auth import get_user_model
from django.views.generic import TemplateView
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.communication.builtins.voip.controller import callback_url


@router.register(
    path="communication/voip/", url_name="voip_connections", name="VoIP connections"
)
class VoIPConnectionsView(BaseBloomerpView, TemplateView):
    """Show authorized account setup, synchronization and local staff assignments."""

    template_name = "views/communication/voip_connections.html"

    def has_permission(self) -> bool:
        """Allow active staff to manage their own carrier configuration."""
        user = self.request.user
        return user.is_authenticated and user.is_active and user.is_staff

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Expose callback configuration without serializing carrier credentials."""
        context = super().get_context_data(**kwargs)
        rows = []
        for connection in (
            VoIPAccessManager(self.request.user).get_connections().order_by("name")
        ):
            urls = (
                {
                    f"{kind}_url": callback_url(connection, kind)
                    for kind in ("voice", "sms", "call_status")
                }
                if connection.settings.get("public_url")
                else {}
            )
            rows.append(
                {
                    "connection": connection,
                    "numbers": connection.numbers.prefetch_related("assigned_users"),
                    "staff": get_user_model().objects.filter(
                        is_staff=True, is_active=True
                    ),
                    **urls,
                }
            )
        context["connections"] = rows
        return context
