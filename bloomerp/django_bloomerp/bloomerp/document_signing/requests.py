"""Create requests and record signer values, consent, audit evidence, and completion."""

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from ipaddress import ip_address
from pathlib import PurePath
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from bloomerp.communication.builtins.emails.base_adapter import (
    EmailSendResult,
    EmailSendUnconfirmed,
)
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.builtins.emails.sending import (
    outbound_message_id,
    store_outbound_email,
)
from bloomerp.forms.document_signing.sign_document import (
    SIGNING_CONSENT,
    SignDocumentForm,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.document_signing import (
    SignatureEvent,
    SignatureLayout,
    SignatureLayoutField,
    SignatureLayoutRole,
    SignaturePreparation,
    SignaturePreparationField,
    SignaturePreparationRole,
    SignatureRecipient,
    SignatureRequest,
    SignatureRequestField,
)
from bloomerp.models.document_signing.definition import SignatureFieldType
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.email_composer_services import accessible_email_accounts
from bloomerp.utils.rich_text import sanitize_html

from .access import (
    DISPATCH_FIELDS,
    LAYOUT_FIELDS,
    LAYOUT_PLACEMENT_FIELDS,
    LAYOUT_ROLE_FIELDS,
    PREPARATION_FIELDS,
    PREPARATION_PLACEMENT_FIELDS,
    PREPARATION_ROLE_FIELDS,
    RECIPIENT_FIELDS,
    REQUEST_FIELD_FIELDS,
    REQUEST_FIELDS,
    can_prepare,
    get_invited_recipient,
    get_signing_preparation,
    get_signing_recipient,
    require_create_request,
    require_sign,
    require_signing_access,
    signing_invitation,
)
from .pdf import read_pdf_content, render_signed_pdf, signing_pdf_reader

logger = logging.getLogger(__name__)


def _snapshot_pdf(
    file: FileNode,
    placements: Sequence[SignatureLayoutField | SignaturePreparationField],
    manager: UserPolicyManager,
    placement_fields: tuple[str, ...],
) -> bytes:
    """Read the authorized PDF and validate readable placements against its actual page count."""
    content = read_pdf_content(file)
    page_count = len(signing_pdf_reader(content).pages)
    for placement in placements:
        require_signing_access(
            placement, manager, BloomerpPermission.VIEW, placement_fields
        )
        if placement.page_number > page_count:
            raise ValidationError("A signing field refers to a page outside the PDF.")
    return content


def _snapshot_values(
    file: FileNode,
    source: SignatureLayout | SignaturePreparation,
    content: bytes,
    manager: UserPolicyManager,
) -> dict[str, Any]:
    """Build one PDF digest and source-provenance snapshot for any request creation path."""
    prepared = isinstance(source, SignaturePreparation)
    layout = source.source_layout if prepared else source
    if layout:
        require_signing_access(layout, manager, BloomerpPermission.VIEW, LAYOUT_FIELDS)
    return {
        "title": source.title if prepared else file.name[:255],
        "original_file": file,
        "original_sha256": sha256(content).hexdigest(),
        "source_preparation": source if prepared else None,
        "source_preparation_revision": source.revision if prepared else None,
        "source_layout": layout,
        "source_layout_name": layout.name if layout else "",
        "source_layout_revision": layout.revision if layout else None,
    }


def _create_recipient(
    request: SignatureRequest,
    role: SignatureLayoutRole | SignaturePreparationRole,
    assignment: dict[str, Any],
    manager: UserPolicyManager,
) -> SignatureRecipient:
    """Create one role and identity snapshot and enforce its recipient-create permissions."""
    recipient = SignatureRecipient.objects.create(
        request=request,
        role_key=role.key,
        role_label=role.label,
        signing_order=role.signing_order
        if isinstance(role, SignaturePreparationRole)
        else role.default_signing_order,
        **assignment,
    )
    require_signing_access(recipient, manager, BloomerpPermission.ADD, RECIPIENT_FIELDS)
    return recipient


def _copy_request_fields(
    request: SignatureRequest,
    placements: Sequence[SignatureLayoutField | SignaturePreparationField],
    recipients: Mapping[UUID, SignatureRecipient],
    manager: UserPolicyManager,
) -> None:
    """Copy normalized placements into recipient-owned fields without retaining mutable geometry."""
    for placement in placements:
        field = SignatureRequestField.objects.create(
            request=request,
            recipient=recipients[placement.role_id],
            **{
                name: getattr(placement, name)
                for name in PREPARATION_PLACEMENT_FIELDS
                if name not in {"preparation", "role"}
            },
        )
        require_signing_access(
            field, manager, BloomerpPermission.ADD, REQUEST_FIELD_FIELDS
        )


def create_signature_request(
    manager: UserPolicyManager,
    file: FileNode,
    source: SignatureLayout | SignaturePreparation,
    revision: int,
    submission_id: UUID,
    assignments: dict[str, dict[str, Any]],
    sender: EmailAccount | None,
    content: str,
    expires_at: datetime | None,
    evidence: dict[str, Any],
    *,
    draft_only: bool = False,
    request_id: UUID | None = None,
    assign_only: bool = False,
) -> SignatureRequest:
    """Save a draft, activate its role assignments, or dispatch one stable signing request."""
    identity = request_id or uuid5(
        NAMESPACE_URL, f"bloomerp:dispatch:{manager.user.pk}:{submission_id}"
    )
    if sender is not None and not assign_only:
        if (
            not accessible_email_accounts(manager.user)
            .filter(pk=sender.pk, status="active")
            .exists()
        ):
            raise ValidationError("Choose an accessible, active sending email account.")
        if EMAIL_PROVIDER_REGISTRY.get(sender.provider) is None:
            raise ValidationError("This email account has an unsupported provider.")
    fingerprint = sha256(
        json.dumps(
            {
                "file": str(file.pk),
                "source": source._meta.label_lower,
                "source_id": str(source.pk),
                "revision": revision,
                "sender": str(sender.pk) if sender else None,
                "content": content,
                "expires_at": expires_at.isoformat() if expires_at else None,
                **({"draft_only": True} if draft_only else {}),
                **({"assign_only": True} if assign_only else {}),
                "recipients": {
                    key: {
                        "email": value["email"],
                        "name": value["name"],
                        "user": str(value["user"].pk) if value["user"] else None,
                    }
                    for key, value in assignments.items()
                },
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        source = type(source).objects.select_for_update().get(pk=source.pk)
        if not can_prepare(file, manager):
            raise ValidationError("You cannot read this PDF.")
        existing = (
            SignatureRequest.objects.select_for_update().filter(pk=identity).first()
        )
        if existing is not None:
            require_signing_access(
                existing, manager, BloomerpPermission.VIEW, DISPATCH_FIELDS
            )
            if existing.status != "draft" or draft_only:
                if not existing.events.filter(
                    event_type__in=["created", "sent"],
                    payload__submission_fingerprint=fingerprint,
                ).exists():
                    raise ValidationError(
                        "This submission already created a request. Reopen the dialog to change its recipients or message."
                    )
                return existing
            require_signing_access(
                existing, manager, BloomerpPermission.CHANGE, DISPATCH_FIELDS
            )
            if (
                request_id is None
                or existing.original_file_id != file.pk
                or existing.source_preparation_id != source.pk
                or existing.source_preparation_revision != revision
                or existing.recipients.exists()
            ):
                raise ValidationError(
                    "Choose the saved request's original signing preparation."
                )
        elif request_id is not None:
            raise ValidationError("This saved signing request no longer exists.")
        prepared = isinstance(source, SignaturePreparation)
        require_signing_access(
            source,
            manager,
            BloomerpPermission.VIEW,
            PREPARATION_FIELDS if prepared else LAYOUT_FIELDS,
        )
        if source.revision != revision:
            raise ValidationError(
                "The signing preparation changed. Reopen the dialog before sending."
            )
        if prepared and source.original_file_id != file.pk:
            raise ValidationError("The preparation belongs to another PDF.")
        if file.metadata.extension != "pdf":
            raise ValidationError("Choose a PDF document.")
        if expires_at and expires_at <= timezone.now():
            raise ValidationError("Choose an expiry in the future.")
        roles = list(source.roles.all())
        if not roles or (
            not draft_only and set(assignments) != {role.key for role in roles}
        ):
            raise ValidationError("Choose one recipient for every signer role.")
        placements = list(source.fields.select_related("role"))
        if {field.role_id for field in placements} != {role.pk for role in roles}:
            raise ValidationError("Each signer role needs at least one field.")
        require_create_request(manager)
        content_bytes = _snapshot_pdf(
            file,
            placements,
            manager,
            PREPARATION_PLACEMENT_FIELDS if prepared else LAYOUT_PLACEMENT_FIELDS,
        )
        if (
            existing is not None
            and existing.original_sha256 != sha256(content_bytes).hexdigest()
        ):
            raise ValidationError(
                "The original PDF no longer matches the saved request."
            )
        values = _snapshot_values(file, source, content_bytes, manager)
        for role in roles:
            require_signing_access(
                role,
                manager,
                BloomerpPermission.VIEW,
                PREPARATION_ROLE_FIELDS if prepared else LAYOUT_ROLE_FIELDS,
            )
        values.update(
            email_account=sender, email_content=content, expires_at=expires_at
        )
        if existing is not None:
            values["title"] = existing.title
        if existing is None:
            request = SignatureRequest.objects.create(id=identity, **values)
        else:
            request = existing
            for name, value in values.items():
                setattr(request, name, value)
            request.save()
        require_signing_access(
            request,
            manager,
            BloomerpPermission.ADD if existing is None else BloomerpPermission.CHANGE,
            DISPATCH_FIELDS,
        )
        if existing is None:
            SignatureEvent.objects.create(
                request=request,
                event_type="created",
                payload={
                    "actor_id": str(manager.user.pk),
                    "submission_fingerprint": fingerprint,
                },
                **evidence,
            )
        if draft_only:
            return request
        recipients = {
            role.pk: _create_recipient(request, role, assignments[role.key], manager)
            for role in roles
        }
        _copy_request_fields(request, placements, recipients, manager)
        for recipient in recipients.values():
            SignDocumentForm(
                recipient=recipient, placements=list(recipient.fields.all())
            )
        require_signing_access(
            request, manager, BloomerpPermission.CHANGE, ("status", "sent_at")
        )
        request.status = SignatureRequest.Status.SENT
        request.sent_at = timezone.now()
        request.save()
        SignatureEvent.objects.create(
            request=request,
            event_type="sent",
            payload={
                "actor_id": str(manager.user.pk),
                "delivery": "links" if assign_only else "email" if sender else "none",
                "submission_fingerprint": fingerprint,
            },
            **evidence,
        )
        return request


def send_signature_emails(
    manager: UserPolicyManager,
    request: SignatureRequest,
    origin: str,
    *,
    sender: EmailAccount | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """Deliver new or saved invitations once, retaining accepted and uncertain delivery outcomes."""
    require_signing_access(request, manager, BloomerpPermission.VIEW, DISPATCH_FIELDS)
    if sender is not None or content is not None:
        require_signing_access(
            request,
            manager,
            BloomerpPermission.CHANGE,
            ("email_account", "email_content"),
        )
    if not can_prepare(request.original_file, manager):
        raise ValidationError("You cannot read this PDF.")
    account_id = sender.pk if sender is not None else request.email_account_id
    if account_id is None:
        return {"status": "created", "request_id": str(request.pk), "deliveries": []}
    account = (
        accessible_email_accounts(manager.user)
        .filter(pk=account_id, status="active")
        .first()
    )
    if account is None:
        raise ValidationError("The sending email account is no longer available.")
    provider = EMAIL_PROVIDER_REGISTRY.get(account.provider)
    if provider is None:
        raise ValidationError("This email account has an unsupported provider.")
    message = sanitize_html(request.email_content if content is None else content)
    subject = _("Signature requested: %(title)s") % {
        "title": " ".join(request.title.split())
    }
    recipients = list(request.recipients.all())
    for recipient in recipients:
        require_signing_access(
            recipient, manager, BloomerpPermission.VIEW, RECIPIENT_FIELDS
        )
        if recipient.status != "signed" and not recipient.email_delivery:
            if not recipient.email:
                raise ValidationError("Every email recipient needs an email address.")
            require_signing_access(
                recipient, manager, BloomerpPermission.CHANGE, ("email_delivery",)
            )
    outcomes: list[dict[str, str]] = []
    for candidate in recipients:
        identity = candidate.pk
        with transaction.atomic():
            locked = SignatureRequest.objects.select_for_update().get(pk=request.pk)
            if locked.status not in {"sent", "completed"} or (
                locked.expires_at and locked.expires_at <= timezone.now()
            ):
                raise ValidationError("This signing request is no longer open.")
            recipient = locked.recipients.get(pk=identity)
            require_signing_access(
                recipient, manager, BloomerpPermission.VIEW, RECIPIENT_FIELDS
            )
            state = recipient.email_delivery.get("status", "pending")
            if (
                state in {"accepted", "unconfirmed", "sending"}
                or recipient.status == "signed"
            ):
                outcomes.append({"email": recipient.email, "status": state})
                continue
            require_signing_access(
                recipient, manager, BloomerpPermission.CHANGE, ("email_delivery",)
            )
            recipient.email_delivery = {
                "status": "sending",
                "started_at": timezone.now().isoformat(),
            }
            recipient.save()
        url = origin.rstrip("/") + reverse(
            "signature_requests_detail_invitation",
            kwargs={"pk": recipient.request_id, "token": signing_invitation(recipient)},
        )
        body = render_to_string(
            "document_signing/invitation_email.html",
            {
                "recipient": recipient,
                "signing_request": request,
                "signing_url": url,
                "email_content": message,
            },
        )
        adapter = provider.adapter_class(account)
        result: str | EmailSendResult | None = None
        state = "accepted"
        try:
            result = adapter.send_email(
                to=[recipient.email],
                subject=subject,
                body_html=body,
                body_text=f"{strip_tags(body)}\n\n{url}",
            )
        except EmailSendUnconfirmed as error:
            state, result = "unconfirmed", error.result
        except Exception:
            # A transport failure may occur after provider acceptance; never resend it automatically.
            state = "unconfirmed"
            logger.exception(
                "Signature invitation delivery could not be confirmed for recipient %s",
                recipient.pk,
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("Could not close the signature email adapter")
        with transaction.atomic():
            locked = SignatureRequest.objects.select_for_update().get(pk=request.pk)
            recipient = locked.recipients.get(pk=identity)
            recipient.email_delivery = {
                "status": state,
                "updated_at": timezone.now().isoformat(),
                "message_id": outbound_message_id(result) if result is not None else "",
                "provider": result.model_dump(mode="json")
                if isinstance(result, EmailSendResult)
                else {},
            }
            recipient.save()
            if result is not None:
                store_outbound_email(
                    account=account,
                    result=result,
                    form_data={
                        "to": [recipient.email],
                        "subject": subject,
                    },
                    body_html=body,
                    pending=state == "unconfirmed",
                )
            SignatureEvent.objects.create(
                request=locked,
                recipient=recipient,
                event_type="sent",
                payload={
                    "delivery": "email",
                    "email_account_id": str(account.pk),
                    "email_content": message,
                    "status": state,
                    "message_id": recipient.email_delivery["message_id"],
                },
            )
        outcomes.append({"email": recipient.email, "status": state})
    return {
        "status": "accepted"
        if all(item["status"] == "accepted" for item in outcomes)
        else "unconfirmed",
        "request_id": str(request.pk),
        "deliveries": outcomes,
    }


def signing_evidence(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Retain the direct peer address and bounded user agent without trusting forwarded headers."""
    try:
        peer = str(ip_address(metadata.get("REMOTE_ADDR", "")))
    except ValueError:
        peer = None
    return {
        "ip_address": peer,
        "user_agent": metadata.get("HTTP_USER_AGENT", "")[:2000],
    }


def _record_signing_event(
    recipient: SignatureRecipient,
    event_type: str,
    evidence: dict[str, Any],
    payload: dict[str, Any] | None = None,
    actor: AbstractBloomerpUser | None = None,
) -> None:
    """Append evidence identifying session authentication or use of an emailed capability."""
    SignatureEvent.objects.create(
        request=recipient.request,
        recipient=recipient,
        event_type=event_type,
        payload={
            "actor_id": str(actor.pk) if actor else None,
            "authentication": "session" if actor else "email_link",
            **(payload or {}),
        },
        **evidence,
    )


def create_self_signing_request(
    manager: UserPolicyManager,
    file_id: str,
    preparation_id: UUID,
    revision: int,
    role_key: str,
    evidence: dict[str, Any],
) -> SignatureRecipient:
    """Snapshot one authorized role once per actor/preparation revision without sending email."""
    with transaction.atomic():
        SignaturePreparation.objects.select_for_update().filter(
            pk=preparation_id
        ).first()
        preparation = get_signing_preparation(manager, file_id, preparation_id)
        if preparation.revision != revision:
            raise ValidationError("The preparation changed. Reload it before signing.")
        role = preparation.roles.filter(key=role_key).first()
        if role is None:
            raise ValidationError("Choose a role from this preparation.")
        require_signing_access(
            role, manager, BloomerpPermission.VIEW, PREPARATION_ROLE_FIELDS
        )
        identity = uuid5(
            NAMESPACE_URL,
            f"bloomerp:self-signing:{preparation.pk}:{revision}:{role.key}:{manager.user.pk}",
        )
        existing = SignatureRequest.objects.filter(pk=identity).first()
        if existing is not None:
            require_signing_access(
                existing, manager, BloomerpPermission.VIEW, REQUEST_FIELDS
            )
            return existing.recipients.get(user=manager.user, role_key=role.key)
        require_create_request(manager)
        placements = list(preparation.fields.filter(role=role))
        if not placements:
            raise ValidationError(
                "Add at least one field to the selected role before signing."
            )
        content = _snapshot_pdf(
            preparation.original_file, placements, manager, PREPARATION_PLACEMENT_FIELDS
        )
        request = SignatureRequest.objects.create(
            id=identity,
            **_snapshot_values(
                preparation.original_file, preparation, content, manager
            ),
        )
        require_signing_access(request, manager, BloomerpPermission.ADD, REQUEST_FIELDS)
        recipient = _create_recipient(
            request,
            role,
            {
                "user": manager.user,
                "name": (manager.user.get_full_name() or str(manager.user))[:255],
                "email": manager.user.email or "",
            },
            manager,
        )
        _copy_request_fields(request, placements, {role.pk: recipient}, manager)
        _record_signing_event(
            recipient,
            SignatureEvent.EventType.CREATED,
            evidence,
            {"mode": "self", "preparation_revision": revision},
            actor=manager.user,
        )
        request.status = SignatureRequest.Status.SENT
        request.sent_at = timezone.now()
        request.save()
        _record_signing_event(
            recipient,
            SignatureEvent.EventType.SENT,
            evidence,
            {"delivery": "in_app", "email_sent": False},
            actor=manager.user,
        )
        return recipient


def complete_signing(
    manager: UserPolicyManager | None,
    recipient_id: str,
    data: dict[str, Any],
    evidence: dict[str, Any],
    invitation: str | None = None,
) -> SignatureRequest:
    """Accept one signer's complete response once, rolling back records and new bytes on failure."""
    output: FileNode | None = None
    try:
        with transaction.atomic():
            if invitation is not None:
                recipient = get_invited_recipient(invitation)
                if str(recipient.pk) != str(recipient_id):
                    raise ValidationError("This link belongs to another signer.")
                actor = None
            elif manager is not None:
                recipient = get_signing_recipient(manager, recipient_id)
                actor = manager.user
            else:
                raise ValidationError(
                    "An authenticated signer or invitation is required."
                )
            request = SignatureRequest.objects.select_for_update().get(
                pk=recipient.request_id
            )
            recipient = SignatureRecipient.objects.select_for_update().get(
                pk=recipient.pk
            )
            recipient.request = request
            if recipient.status == SignatureRecipient.Status.SIGNED:
                return request
            if (
                request.status != SignatureRequest.Status.SENT
                or recipient.status not in {"pending", "viewed"}
            ):
                raise ValidationError("This signing request is no longer open.")
            if request.expires_at and request.expires_at <= timezone.now():
                raise ValidationError("This signing request has expired.")
            if data.get("consent") is not True:
                raise ValidationError(
                    "Agree to electronic signing before confirming your signature."
                )
            fields = list(recipient.fields.all())
            submitted = data.get("values")
            if not isinstance(submitted, dict) or set(submitted) - {
                str(field.pk) for field in fields
            }:
                raise ValidationError("Submit only the fields assigned to this signer.")
            if invitation is None:
                require_sign(recipient, manager)
            for field in fields:
                allowed = (
                    (str, bool, type(None), dict)
                    if field.field_type == SignatureFieldType.SIGNATURE
                    else (str, bool, type(None))
                )
                if not isinstance(submitted.get(str(field.pk)), allowed):
                    raise ValidationError(
                        "Submit text, checkbox responses or drawn signature strokes for their assigned fields."
                    )
            form_data = {
                f"field_{field.pk.hex}": submitted.get(str(field.pk))
                for field in fields
            }
            form = SignDocumentForm(
                recipient=recipient,
                placements=fields,
                data={**form_data, "consent": data.get("consent")},
            )
            if not form.is_valid():
                messages = [
                    f"{form.fields[name].label}: {', '.join(errors)}"
                    for name, errors in form.errors.items()
                ]
                raise ValidationError(" ".join(messages))
            values = form.values()
            content = read_pdf_content(request.original_file)
            if sha256(content).hexdigest() != request.original_sha256:
                raise ValidationError(
                    "The original PDF no longer matches the signing snapshot."
                )
            remaining = (
                request.recipients.exclude(pk=recipient.pk)
                .exclude(status=SignatureRecipient.Status.SIGNED)
                .exists()
            )
            signed_bytes = None
            if not remaining:
                all_fields = list(request.fields.all())
                all_values = {str(field.pk): field.value for field in all_fields}
                signed_bytes = render_signed_pdf(
                    content, all_fields, {**all_values, **values}
                )
            now = timezone.now()
            for field in fields:
                field.value = values[str(field.pk)]
                field.filled_at = now if field.has_value else None
                field.save()
                if field.has_value:
                    _record_signing_event(
                        recipient,
                        SignatureEvent.EventType.FIELD_COMPLETED,
                        evidence,
                        {"field_id": str(field.pk), "field_key": field.key},
                        actor=actor,
                    )
            recipient.consent_text = str(SIGNING_CONSENT)
            recipient.consented_at = now
            recipient.signed_at = now
            recipient.status = SignatureRecipient.Status.SIGNED
            recipient.save()
            _record_signing_event(
                recipient,
                SignatureEvent.EventType.CONSENTED,
                evidence,
                {"text": recipient.consent_text},
                actor=actor,
            )
            _record_signing_event(
                recipient,
                SignatureEvent.EventType.SIGNED,
                evidence,
                {"original_sha256": request.original_sha256},
                actor=actor,
            )
            if signed_bytes is not None:
                name = f"{PurePath(request.original_file.name).stem[:240]}-signed.pdf"
                output = FileNode(
                    name=name,
                    kind="FILE",
                    content=ContentFile(signed_bytes, name=name),
                )
                output.save()
                request.signed_file = output
                request.signed_sha256 = sha256(signed_bytes).hexdigest()
                request.completed_at = now
                request.status = SignatureRequest.Status.COMPLETED
                request.save()

                output.create_reference(request)

                for reference in request.original_file.get_references():
                    output.create_reference(reference.content_object)

                _record_signing_event(
                    recipient,
                    SignatureEvent.EventType.COMPLETED,
                    evidence,
                    {"signed_sha256": request.signed_sha256},
                    actor=actor,
                )
            return request
    except Exception:
        if output is not None and output.content._committed:
            output.content.delete(save=False)
        raise
