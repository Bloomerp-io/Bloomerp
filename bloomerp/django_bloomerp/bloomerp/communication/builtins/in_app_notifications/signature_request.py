"""Deliver signing invitations through internal recipients' notification inboxes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from bloomerp.communication.builtins.in_app_notifications.base import (
    BaseSystemMessageType,
    SystemMessageItemData,
)
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
)
from bloomerp.utils.rich_text import sanitize_html

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem
    from bloomerp.models.document_signing import (
        SignatureEvent,
        SignatureRecipient,
        SignatureRequest,
    )


class SignatureRequestSystemMessage(BaseSystemMessageType):
    """Keep a durable invitation and offer signing to its assigned internal recipient."""

    @classmethod
    def build_item_data(cls, data: dict[str, Any]) -> SystemMessageItemData:
        """Snapshot the request title, message and role without storing invitation tokens."""
        return SystemMessageItemData(
            title=_("Signature requested: %(title)s")
            % {"title": data["request_title"]},
            snippet=_("Your signature is required as %(role)s.")
            % {"role": data["role_label"]},
            related_item_id=f"signature_request:{data['recipient_id']}",
            raw_meta_data={
                "request_id": str(data["request_id"]),
                "recipient_id": str(data["recipient_id"]),
                "request_title": data["request_title"],
                "role_label": data["role_label"],
                "email_content": sanitize_html(data.get("email_content", "")),
            },
        )

    @classmethod
    def render(cls, item: InboxItem, request: HttpRequest | None = None) -> str:
        """Render the message and delegate signing only to the assigned, eligible recipient."""
        from bloomerp.document_signing.access import signing_invitation
        from bloomerp.models.document_signing import SignatureRecipient
        from bloomerp.permissions.definition import BloomerpPermission
        from bloomerp.permissions.manager import UserPolicyManager

        metadata = item.raw_meta_data or {}
        context: dict[str, Any] = {
            "item": item,
            "email_content": sanitize_html(metadata.get("email_content", "")),
        }
        if request is not None and request.user.is_authenticated:
            try:
                recipient_id = UUID(str(metadata.get("recipient_id")))
            except ValueError:
                recipient_id = None
            recipient = (
                SignatureRecipient.objects.select_related("request")
                .filter(pk=recipient_id, user_id=request.user.pk)
                .first()
            )
            if recipient is not None:
                if "email_content" not in metadata:
                    context["email_content"] = sanitize_html(
                        recipient.request.email_content
                    )
                manager = UserPolicyManager(request.user)
                if manager.has_access_to_object(
                    recipient.request, BloomerpPermission.VIEW
                ):
                    context["status_url"] = recipient.request.get_absolute_url()
                if (
                    _ready_recipients(recipient.request)
                    .filter(pk=recipient.pk)
                    .exists()
                ):
                    context["sign_url"] = reverse(
                        "components_document_signing_invitation",
                        kwargs={"recipient_id": signing_invitation(recipient)},
                    )
        return render_to_string(
            "inbox_items/signature_request.html", context, request=request
        )


def _ready_recipients(
    signing_request: SignatureRequest,
) -> QuerySet[SignatureRecipient]:
    """Select active internal signers at the earliest unfinished signing order."""
    recipients = signing_request.recipients.all()
    if signing_request.status != "sent" or (
        signing_request.expires_at and signing_request.expires_at <= timezone.now()
    ):
        return recipients.none()
    order = (
        recipients.exclude(status="signed")
        .order_by("signing_order")
        .values_list("signing_order", flat=True)
        .first()
    )
    return recipients.filter(
        user__is_active=True,
        status__in=["pending", "viewed"],
        signing_order=order,
    )


def should_notify_signature_request(
    *, instance: SignatureEvent, created: bool, raw: bool = False, **kwargs: Any
) -> bool:
    """Notify eligible signers after delivery starts, leaving manual role assignment quiet."""
    if not created or raw or instance.event_type not in {"sent", "signed"}:
        return False
    events = instance.request.events.filter(event_type="sent")
    return (
        not events.filter(payload__delivery="links").exists()
        or events.filter(payload__delivery="email").exists()
    )


def resolve_signature_request_folders(
    *, instance: SignatureEvent, **kwargs: Any
) -> QuerySet[InboxFolder]:
    """Resolve assigned users' owned inboxes; the handler selects the current signing order."""
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.document_signing import SignatureRecipient

    return InboxFolder.objects.filter(
        type="in_app_notifications",
        inbox__source_object__isnull=True,
        inbox__user_id__in=SignatureRecipient.objects.filter(
            request_id=instance.request_id, user__is_active=True
        ).values("user_id"),
    ).select_related("inbox")


def handle_signature_request(
    folders: QuerySet[InboxFolder], *, instance: SignatureEvent, **kwargs: Any
) -> InboxSourceExecutionResult:
    """Persist one invitation per recipient and folder, broadcasting only after commit."""
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage
    from bloomerp.models.document_signing import SignatureRequest

    deliveries = []
    with transaction.atomic():
        signing_request = (
            SignatureRequest.objects.select_for_update()
            .filter(pk=instance.request_id)
            .first()
        )
        if signing_request is None:
            return InboxSourceExecutionResult(
                outcome="skipped", reason="Request removed"
            )
        by_user: dict[int, list[SignatureRecipient]] = {}
        for recipient in _ready_recipients(signing_request):
            by_user.setdefault(recipient.user_id, []).append(recipient)
        for folder in folders:
            items = []
            for recipient in by_user.get(folder.inbox.user_id, []):
                if folder.inbox_items.filter(
                    item_type="notification",
                    related_item_id=f"signature_request:{recipient.pk}",
                    raw_meta_data__system_message_type="signature_request",
                ).exists():
                    continue
                message = (
                    recipient.events.filter(
                        event_type="sent", payload__delivery="email"
                    )
                    .order_by("-datetime_created", "-pk")
                    .values_list("payload__email_content", flat=True)
                    .first()
                )
                items.append(
                    SystemMessage.create_item(
                        message_type="signature_request",
                        folder=folder,
                        data={
                            "request_id": str(signing_request.pk),
                            "recipient_id": str(recipient.pk),
                            "request_title": signing_request.title,
                            "role_label": recipient.role_label,
                            "email_content": signing_request.email_content
                            if message is None
                            else message,
                        },
                    )
                )
            if items:
                deliveries.append(
                    InboxSourceDelivery(folder=folder, items=tuple(items))
                )
    return InboxSourceExecutionResult(
        deliveries=tuple(deliveries),
        defer_notifications_until_commit=True,
        plain_text_notifications=True,
    )
