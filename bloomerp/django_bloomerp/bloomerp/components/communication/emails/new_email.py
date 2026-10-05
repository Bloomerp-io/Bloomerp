"""Render and send the shared inbox/object email composer."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from bloomerp.communication.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.router import router
from bloomerp.services.email_composer_requests import (
    _get_attachments, _get_form_data, _join_recipients, _resolve_account,
    _resolve_draft, _validate_form_data, resolve_inbox_folder,
)
from bloomerp.services.email_composer_services import (
    accessible_email_accounts, email_fields_for_object, render_email_body,
    resolve_email_object, resolve_email_templates,
)
from bloomerp.utils.requests import render_message

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


@router.register(path="components/communication/emails/new_email", url_name="components_new_email")
@login_required
@require_http_methods(["GET", "POST"])
def new_email(request: HttpRequest, inbox_folder_or_id: InboxFolder | str | None = None) -> HttpResponse:
    """Render or send the same composer from an inbox or an authorized object."""
    wants_json = "application/json" in request.headers.get("Accept", "")
    try:
        folder = resolve_inbox_folder(request, inbox_folder_or_id)
        account = _resolve_account(request, folder)
        data = request.POST if request.method == "POST" else request.GET
        obj = resolve_email_object(request.user, data)
        if account is None:
            raise ValidationError(_("No accessible email account is available. Add an account or update your access."))
        if request.method == "POST":
            return _send_new_email(request, folder, account, obj)
        recipient = ""
        if obj is not None:
            fields = email_fields_for_object(request.user, obj)
            chosen = next((field for field in fields if field["name"] == data.get("email_field")), None)
            if chosen is None:
                raise ValidationError(_("Select a readable, populated email field."))
            recipient = chosen["value"]
        return _render_email_composer(request, folder, account, obj, {"to": recipient})
    except (ValidationError, ValueError) as exc:
        errors = exc.messages if isinstance(exc, ValidationError) else [_("Invalid email request.")]
        if wants_json:
            return JsonResponse({"errors": errors}, status=400)
        return render_message(request, " ".join(errors), "error")


def _send_new_email(
    request: HttpRequest, inbox_folder: InboxFolder | None,
    email_account: EmailAccount, obj: models.Model | None,
) -> HttpResponse:
    """Validate edited content, send once, and discard the owner's draft on success."""
    form_data = _get_form_data(request)
    errors = _validate_form_data(form_data)
    if errors:
        raise ValidationError(errors)
    templates = resolve_email_templates(request.user, obj, request.POST)
    draft = _resolve_draft(request)
    body = render_email_body(request.user, obj, templates, request.POST)
    provider = EMAIL_PROVIDER_REGISTRY.get(email_account.provider)
    if provider is None:
        raise ValidationError(_("This email account has an unsupported provider."))
    adapter = provider.adapter_class(email_account)
    try:
        adapter.send_email(
            to=form_data["to"], cc=form_data["cc"], bcc=form_data["bcc"],
            subject=form_data["subject"], body_html=body, attachments=_get_attachments(request),
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    if draft is not None:
        draft.delete()
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"message": _("Email sent successfully.")})
    return render_message(request, _("Email sent successfully."), "success")


def _render_email_composer(
    request: HttpRequest, inbox_folder: InboxFolder | None,
    email_account: EmailAccount, obj: models.Model | None,
    form_data: dict[str, Any],
) -> HttpResponse:
    """Provide contextual accounts and document templates to the reusable editor."""
    return render(request, "components/communication/emails/email_editor.html", {
        "mode": "new", "title": _("New email"), "submit_label": _("Send"),
        "inbox_folder": inbox_folder, "email_account": email_account,
        "from_email": email_account.email_address,
        "email_accounts": accessible_email_accounts(request.user),
        "email_object": obj,
        "email_content_type_id": ContentType.objects.get_for_model(obj).pk if obj is not None else "",
        "to": _join_recipients(form_data.get("to", [])),
        "subject": form_data.get("subject", ""), "body": form_data.get("body", ""),
        "form_action": reverse("components_new_email"), "send_enabled": True,
        "enhanced_composer": True,
    })
