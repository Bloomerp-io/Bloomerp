"""Reconfigure an existing email account through the shared account wizard."""

from typing import Any
from django.forms.models import model_to_dict
from django.http import HttpRequest

from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.communication.create_email_account import (
    CRUDEmailAccountMixin,
    EmailAccountSettingsForm,
    PROVIDER_SESSION_KEY,
    SETTINGS_SESSION_KEY,
)
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


@router.register(
    path="reconfigure/",
    route_type="detail",
    models=[EmailAccount],
    url_name="reconfigure_email_account",
    name="Reconfigure email account",
)
class ReconfigureEmailAccountView(CRUDEmailAccountMixin, BaseBloomerpDetailView):
    """Reuse all setup steps with current object and field permission enforcement."""

    is_detail_view = True

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        """Keep each account's wizard state separate from creation and other accounts."""
        self.session_key = f"email_account_reconfigure_{kwargs['pk']}"
        super().setup(request, *args, **kwargs)
        self.object = self.get_object()

    def get_account(self) -> EmailAccount:
        """Reuse the current detail object throughout the account wizard."""
        return self.object

    def has_permission(self) -> bool:
        """Require account change access and preload authorized settings without secrets."""
        manager = UserPolicyManager(self.request.user)
        fields = [*EmailAccountSettingsForm.Meta.fields, "provider", "mailboxes"]
        allowed = manager.has_access_to_object(
            self.object, BloomerpPermission.CHANGE, fields=fields
        )
        if allowed and self.orchestrator.get_session_data(PROVIDER_SESSION_KEY) is None:
            self.orchestrator.set_session_data(PROVIDER_SESSION_KEY, self.object.provider)
            settings = model_to_dict(self.object, fields=EmailAccountSettingsForm.Meta.fields)
            for name in EmailAccount.SECRET_FIELDS:
                settings.pop(name, None)
            self.orchestrator.set_session_data(SETTINGS_SESSION_KEY, settings)
        return allowed
