"""Shared mailbox authorization lifecycle, dispatched only through provider definitions."""

from __future__ import annotations

import hashlib
import json
import secrets
from copy import copy
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from bloomerp.communication.utils.crypto import (
    decrypt_email_secret,
    encrypt_email_secret,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.email_authorization_request import (
    EmailAuthorizationRequest,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

from .mailboxes import merge_mailboxes, normalize_mailboxes
from .provider_definition import EmailProviderDefinition
from .registry import EMAIL_PROVIDER_REGISTRY

AUTHORIZATION_SESSION_KEY = "email_authorization_browser"
AUTHORIZATION_LIFETIME = timedelta(minutes=10)


def authorization_callback_uri(request: HttpRequest) -> str:
    """Return the fixed HTTPS callback on an explicitly allowlisted instance host."""
    uri = request.build_absolute_uri(reverse("email_authorization_callback"))
    parsed = urlsplit(uri)
    allowed = {
        host.casefold()
        for host in settings.ALLOWED_HOSTS
        if not host.startswith(("*", "."))
    }
    if parsed.scheme != "https" or parsed.hostname.casefold() not in allowed:
        raise ValidationError(
            _(
                "Email authorization requires HTTPS and an explicit instance host in ALLOWED_HOSTS."
            )
        )
    return uri


def _digest(value: str) -> str:
    """Hash an unpredictable state or browser binding before storing it."""
    return hashlib.sha256(value.encode()).hexdigest()


def account_configuration_fingerprint(account: EmailAccount) -> str:
    """Detect credential/provider edits while an authorization is in flight."""
    values = {
        name: getattr(account, name)
        for name in (
            "provider",
            "email_address",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_tenant_id",
        )
    }
    values["authorization_revision"] = account.extra_settings.get(
        "authorization_revision"
    )
    return _digest(json.dumps(values, sort_keys=True))


def require_account_authorization(
    request: HttpRequest, account: EmailAccount | None
) -> None:
    """Apply existing create or object/field change permissions at every lifecycle boundary."""
    from bloomerp.views.communication.create_email_account import (
        EmailAccountSettingsForm,
    )

    if not request.user.is_authenticated:
        raise PermissionDenied
    manager = UserPolicyManager(request.user)
    if account is None:
        allowed = manager.has_global_permission(EmailAccount, BloomerpPermission.ADD)
    else:
        allowed = manager.has_access_to_object(
            account,
            BloomerpPermission.CHANGE,
            fields=[*EmailAccountSettingsForm.Meta.fields, "provider", "mailboxes"],
        )
    if not allowed:
        raise PermissionDenied


def begin_authorization(
    request: HttpRequest,
    *,
    provider: EmailProviderDefinition,
    candidate: EmailAccount,
    account: EmailAccount | None,
    wizard_key: str,
    account_settings: dict[str, Any],
) -> HttpResponse:
    """Save encrypted, expiring setup data before redirecting to provider consent."""
    require_account_authorization(request, account)
    callback_uri = authorization_callback_uri(request)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    browser = request.session.get(AUTHORIZATION_SESSION_KEY)
    if not browser:
        browser = secrets.token_urlsafe(32)
        request.session[AUTHORIZATION_SESSION_KEY] = browser
    adapter = provider.adapter_class(candidate)
    try:
        location = provider.authorization.start(
            adapter,
            redirect_uri=callback_uri,
            state=state,
            code_verifier=verifier,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    if urlsplit(location).scheme != "https":
        raise ValidationError(_("The provider returned an invalid authorization URL."))
    payload = {
        "provider": provider.key,
        "settings": account_settings,
        "verifier": verifier,
        "wizard_key": wizard_key,
        "return_url": request.path,
        "configuration": account_configuration_fingerprint(account)
        if account
        else None,
    }
    EmailAuthorizationRequest.objects.filter(expires_at__lte=timezone.now()).delete()
    EmailAuthorizationRequest.objects.create(
        state_digest=_digest(state),
        user=request.user,
        account=account,
        session_digest=_digest(browser),
        redirect_uri=callback_uri,
        payload=encrypt_email_secret(json.dumps(payload)),
        expires_at=timezone.now() + AUTHORIZATION_LIFETIME,
    )
    wizard = dict(request.session.get(wizard_key) or {})
    wizard.pop("mailboxes", None)
    wizard["authorization_pending"] = _digest(state)
    wizard.pop("authorization_complete", None)
    request.session[wizard_key] = wizard
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse()
        response["HX-Redirect"] = location
    else:
        response = HttpResponseRedirect(location)
    response["Cache-Control"] = "no-store"
    return response


def complete_authorization(request: HttpRequest) -> HttpResponse:
    """Consume bound state once, dispatch the provider exchange and resume mailbox mapping."""
    state = request.GET.get("state", "")
    browser = request.session.get(AUTHORIZATION_SESSION_KEY, "")
    if not state or not browser or not request.user.is_authenticated:
        raise PermissionDenied
    callback_uri = authorization_callback_uri(request)
    with transaction.atomic():
        attempt = (
            EmailAuthorizationRequest.objects.select_for_update()
            .filter(
                state_digest=_digest(state),
                user=request.user,
                session_digest=_digest(browser),
                redirect_uri=callback_uri,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if attempt is None:
            raise PermissionDenied
        payload = json.loads(decrypt_email_secret(attempt.payload))
        account = attempt.account
        require_account_authorization(request, account)
        wizard_key = payload["wizard_key"]
        wizard = dict(request.session.get(wizard_key) or {})
        if wizard.get("authorization_pending") != attempt.state_digest:
            raise PermissionDenied
        if account and payload["configuration"] != account_configuration_fingerprint(
            account
        ):
            raise PermissionDenied
        attempt.delete()

    provider = EMAIL_PROVIDER_REGISTRY.get(payload["provider"])
    if provider is None or provider.authorization is None:
        raise PermissionDenied
    wizard.pop("authorization_pending", None)
    error = None
    if request.GET.get("error") or not request.GET.get("code"):
        error = _(
            "Authorization was cancelled or denied. Connect again to grant mailbox access."
        )
    else:
        candidate = EmailAccount(provider=provider.key)
        if account:
            candidate.pk = account.pk
            candidate.extra_settings = dict(account.extra_settings)
            candidate.mailboxes = account.mailboxes
        for name, value in payload["settings"].items():
            if name != "set_as_default":
                setattr(candidate, name, value)
        adapter = provider.adapter_class(candidate)
        try:
            provider.authorization.complete(
                adapter,
                code=request.GET["code"],
                redirect_uri=callback_uri,
                code_verifier=payload["verifier"],
            )
            names = adapter.validate_connection()
            defaults = (
                provider.mailbox_defaults(adapter) if provider.mailbox_defaults else {}
            )
            previous = normalize_mailboxes(account.mailboxes) if account else {}
            mapping = merge_mailboxes(names, previous, provider_defaults=defaults)
            for field_name in ("access_token", "refresh_token"):
                payload["settings"][field_name] = encrypt_email_secret(
                    getattr(candidate, field_name)
                )
            payload["settings"]["token_expires_at"] = (
                candidate.token_expires_at.isoformat()
                if candidate.token_expires_at
                else None
            )
            payload["settings"]["extra_settings"] = candidate.extra_settings
            payload["settings"]["email_address"] = candidate.email_address
            wizard.update(
                {
                    "provider": provider.key,
                    "settings": payload["settings"],
                    "mailboxes": mapping,
                    "authorization_complete": True,
                    "__wizard_step": 2,
                    "authorization_configuration": payload["configuration"],
                    "authorization_expires": (
                        timezone.now() + AUTHORIZATION_LIFETIME
                    ).isoformat(),
                }
            )
            wizard.pop("__wizard_error", None)
        except Exception:  # noqa: BLE001 -- provider failures must never expose tokens or remote diagnostics.
            error = _(
                "Mailbox authorization failed. Check the application, tenant, consent and mailbox address, then reconnect."
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
    if error:
        wizard.pop("authorization_complete", None)
        wizard.pop("mailboxes", None)
        wizard["__wizard_step"] = 1
        wizard["__wizard_error"] = {
            "step": 1,
            "message": str(error),
            "title": str(_("Email connection failed")),
        }
    request.session[wizard_key] = wizard
    return HttpResponseRedirect(payload["return_url"])


def disconnect_account(request: HttpRequest, account: EmailAccount) -> None:
    """Stop receiving and remove local authorization through the provider's lifecycle."""
    require_account_authorization(request, account)
    provider = EMAIL_PROVIDER_REGISTRY.get(account.provider)
    if provider is None or provider.authorization is None:
        raise ValidationError(_("This provider does not use account authorization."))
    with transaction.atomic():
        account = EmailAccount.objects.select_for_update().get(pk=account.pk)
        authorized_snapshot = copy(account)
        authorized_snapshot._state = copy(account._state)
        authorized_snapshot._state.adding = True
        account.access_token = ""
        account.refresh_token = ""
        account.token_expires_at = None
        account.sync_enabled = False
        account.status = EmailAccount.Status.DRAFT
        account.next_sync_at = None
        account.validation_error = ""
        account.extra_settings = {
            **account.extra_settings,
            "authorization_revision": secrets.token_hex(16),
        }
        account.save(
            update_fields=[
                "access_token",
                "refresh_token",
                "token_expires_at",
                "sync_enabled",
                "status",
                "next_sync_at",
                "validation_error",
                "extra_settings",
                "datetime_updated",
            ]
        )
        EmailAuthorizationRequest.objects.filter(account=account).delete()
    if provider.authorization.disconnect:
        adapter = provider.adapter_class(authorized_snapshot)
        try:
            provider.authorization.disconnect(adapter)
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
