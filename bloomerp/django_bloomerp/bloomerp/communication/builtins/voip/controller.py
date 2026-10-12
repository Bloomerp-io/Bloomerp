"""Authorized carrier operations and idempotent communication persistence."""

from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.communication.voip import (
    VoIPConnection,
    VoIPNumber,
    PhoneCall,
    PhoneCallEvent,
)
from .access import VoIPAccessManager
from .definition import BaseVoIPAdapter, VoIPContext, VoIPCallData
from .registry import VOIP_PROVIDER_REGISTRY


def adapter_for(connection: VoIPConnection) -> BaseVoIPAdapter:
    """Resolve current credentials only at the trusted server transport boundary."""
    provider = VOIP_PROVIDER_REGISTRY.get(connection.provider)
    if provider is None:
        raise ValidationError(_("Unknown carrier provider."))
    return provider.create_adapter(
        VoIPContext(
            str(connection.pk),
            connection.external_account_id,
            connection.settings,
            connection.get_credentials(),
        )
    )


def callback_url(connection: VoIPConnection, kind: str, **kwargs: Any) -> str:
    """Build signature-stable callback URLs from administrator-supplied public origin."""
    return connection.settings["public_url"].rstrip("/") + reverse(
        f"voip_{kind}", kwargs={"connection_id": connection.pk, **kwargs}
    )


def notify_conversation(conversation_id: UUID) -> None:
    """Invalidate the live conversation after a committed carrier state change."""
    from bloomerp.communication.builtins.instant_messaging.controller import (
        IMController,
    )
    from bloomerp.communication.builtins.instant_messaging.inbox_source import (
        publish_conversation_activity,
    )

    IMController.notify_reactions(conversation_id)
    try:
        publish_conversation_activity(conversation_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Could not project conversation %s into inbox", conversation_id
        )


class VoIPController:
    """Coordinate carrier adapters with line authorization and local persistence."""

    def __init__(self, user: AbstractBloomerpUser) -> None:
        """Bind operations to the authenticated actor and shared access manager."""
        self.user = user
        self.access = VoIPAccessManager(user)

    def synchronize(self, connection_id: UUID) -> VoIPConnection:
        """Validate and synchronize inventory/history without overwriting local labels."""
        connection = self.access.get_connections().filter(pk=connection_id).first()
        if connection is None:
            raise PermissionDenied
        adapter = adapter_for(connection)
        capabilities = adapter.validate_connection()
        numbers = adapter.list_numbers()
        since = (
            connection.last_synced_at - timedelta(days=1)
            if connection.last_synced_at
            else timezone.now() - timedelta(days=30)
        )
        started = timezone.now()
        calls = (
            adapter.sync_calls(since)
            if capabilities.history_sync and connection.sync_enabled
            else ()
        )
        with transaction.atomic():
            connection = VoIPConnection.objects.select_for_update().get(
                pk=connection.pk
            )
            seen = set()
            for remote in numbers:
                number, created = VoIPNumber.objects.get_or_create(
                    connection=connection,
                    provider_number_id=remote.external_id,
                    defaults={"number": remote.number, "name": remote.name},
                )
                if number.number != remote.number:
                    raise ValidationError(
                        _(
                            "A provider number changed its address. Reconcile the line before synchronizing."
                        )
                    )
                number.is_active = True
                number.supports_sms = remote.sms
                number.supports_voice = remote.voice
                number.save()
                if created:
                    number.assigned_users.add(self.user)
                seen.add(number.pk)
            for missing in connection.numbers.exclude(pk__in=seen):
                missing.is_active = False
                missing.save(update_fields=["is_active"])
            connection.settings = {
                **connection.settings,
                "browser_calling": capabilities.browser_calling,
            }
            connection.status = "active"
            connection.validated_at = started
            connection.last_synced_at = started
            connection.save()
            for call in calls:
                reconcile_call(
                    connection,
                    call,
                    f"sync:{call.external_id}:{call.status}:{call.duration}",
                )
        return connection

    def conversation(self, conversation_id: UUID) -> Any:
        """Recheck membership and current line assignment before sending or calling."""
        from bloomerp.communication.builtins.instant_messaging.access import (
            IMAccessManager,
        )

        chat = (
            IMAccessManager(self.user)
            .get_conversations()
            .select_related("voip_number__connection")
            .filter(pk=conversation_id)
            .first()
        )
        if (
            chat is None
            or chat.status == "archived"
            or not self.access.get_numbers().filter(pk=chat.voip_number_id).exists()
        ):
            raise PermissionDenied
        return chat

    def send_message(
        self, conversation_id: UUID, html: str, client_id: str, **kwargs: Any
    ) -> Any:
        """Persist a deduplicated send before network dispatch, never retry an uncertain send."""
        from bloomerp.models.communication.instant_messaging import (
            IMConversation,
            IMMessage,
        )
        from bloomerp.communication.builtins.instant_messaging.content import (
            prepare_content,
        )
        from bloomerp.communication.builtins.instant_messaging.controller import (
            IMController,
        )

        chat = self.conversation(conversation_id)
        if not chat.voip_number.supports_sms or not client_id or len(client_id) > 255:
            raise ValidationError(
                _("SMS is unavailable or the request identifier is invalid.")
            )
        if kwargs.get("reply_to_id") or kwargs.get("thread_root_id"):
            raise ValidationError(_("SMS does not support quoted replies or threads."))
        body, _html = prepare_content(html, self.user, chat)
        if not body or len(body) > 1600:
            raise ValidationError(_("Enter between 1 and 1600 characters."))
        with transaction.atomic():
            IMConversation.objects.select_for_update().get(pk=chat.pk)
            sender = chat.participants.get(user=self.user, left_at__isnull=True)
            existing = chat.messages.filter(sender=sender, client_id=client_id).first()
            if existing:
                return existing
            sequence = (chat.messages.aggregate(last=Max("sequence"))["last"] or 0) + 1
            message = IMMessage.objects.create(
                conversation=chat,
                sender=sender,
                sequence=sequence,
                body=body,
                direction="outbound",
                client_id=client_id,
                status="pending",
            )
            chat.last_activity_at = timezone.now()
            chat.save(update_fields=["last_activity_at"])
        connection = chat.voip_number.connection
        try:
            remote_id = adapter_for(connection).send_sms(
                chat.voip_number.number,
                chat.phone_address,
                body,
                callback_url(connection, "message_status", message_id=message.pk),
            )
        except Exception:
            # The carrier may have accepted a timed-out request. Keep pending for reconciliation.
            raise ValidationError(
                _(
                    "Delivery could not be confirmed. Do not resend until its status is known."
                )
            ) from None
        with transaction.atomic():
            message = IMMessage.objects.select_for_update().get(pk=message.pk)
            message.provider_message_id = remote_id
            if message.status == "pending":
                message.status = "accepted"
            message.sent_at = timezone.now()
            message.save()
        IMController(self.user).notify_message(message.pk)
        return message

    @transaction.atomic
    def cancel_reservation(self, conversation_id: UUID, call_id: UUID) -> PhoneCall:
        """Close an actor's unsubmitted call after browser establishment fails."""
        chat = self.conversation(conversation_id)
        call = (
            PhoneCall.objects.select_for_update()
            .filter(pk=call_id, conversation=chat, handled_by=self.user)
            .first()
        )
        if call is None:
            raise PermissionDenied
        if call.status == "pending" and not call.provider_call_id:
            call.status = "failed"
            call.ended_at = timezone.now()
            call.save(update_fields=["status", "ended_at"])
            project_call(call)
            transaction.on_commit(partial(notify_conversation, chat.pk))
        return call

    def prepare_call(self, conversation_id: UUID, client_id: str) -> PhoneCall:
        """Reserve an authorized outgoing session for signed TwiML dispatch."""
        chat = self.conversation(conversation_id)
        number = chat.voip_number
        if not number.supports_voice or not number.connection.settings.get(
            "browser_calling"
        ):
            raise ValidationError(_("Browser calling is unavailable for this line."))
        if not client_id or len(client_id) > 255:
            raise ValidationError(_("A call request identifier is required."))
        call, created = PhoneCall.objects.get_or_create(
            connection=number.connection,
            client_id=client_id,
            defaults={
                "number": number,
                "conversation": chat,
                "direction": "outbound",
                "from_address": number.number,
                "to_address": chat.phone_address,
                "handled_by": self.user,
                "started_at": timezone.now(),
            },
        )
        if call.conversation_id != chat.pk or call.handled_by_id != self.user.pk:
            raise PermissionDenied
        if created:
            project_call(call)
            notify_conversation(chat.pk)
        return call


@transaction.atomic
def reconcile_call(
    connection: VoIPConnection, remote: VoIPCallData, event_id: str
) -> PhoneCall:
    """Reconcile repeated and out-of-order carrier events while retaining terminal states."""
    from bloomerp.models.communication.instant_messaging import IMConversation

    VoIPConnection.objects.select_for_update().get(pk=connection.pk)
    call = (
        PhoneCall.objects.select_for_update()
        .filter(connection=connection, provider_call_id=remote.external_id)
        .first()
    )
    if call is None:
        number = connection.numbers.filter(
            number=remote.to_address
            if remote.direction == "inbound"
            else remote.from_address
        ).first()
        address = (
            remote.from_address if remote.direction == "inbound" else remote.to_address
        )
        chat = (
            IMConversation.objects.filter(
                voip_number=number, phone_address=address, provider_key="phone"
            ).first()
            if number
            else None
        )
        call = PhoneCall.objects.create(
            connection=connection,
            number=number,
            conversation=chat,
            provider_call_id=remote.external_id,
            parent_call_id=remote.parent_id,
            direction=remote.direction,
            from_address=remote.from_address,
            to_address=remote.to_address,
        )
    event, created = PhoneCallEvent.objects.get_or_create(
        call=call,
        event_id=event_id,
        defaults={"status": remote.status, "occurred_at": timezone.now()},
    )
    if not created:
        return call
    previous = (call.status, call.duration, call.started_at, call.ended_at)
    terminal = {"completed", "busy", "no-answer", "canceled", "failed"}
    ranks = {"pending": 0, "queued": 1, "ringing": 2, "in-progress": 3}
    if call.status not in terminal and (
        remote.status in terminal
        or ranks.get(remote.status, -1) >= ranks.get(call.status, 0)
    ):
        call.status = remote.status
    call.started_at = call.started_at or remote.started_at
    call.ended_at = call.ended_at or remote.ended_at
    call.duration = max(call.duration, remote.duration)
    call.save()
    changed = previous != (call.status, call.duration, call.started_at, call.ended_at)
    if changed and call.conversation_id and not call.parent_call_id:
        project_call(call)
        chat = call.conversation
        chat.last_activity_at = timezone.now()
        chat.save(update_fields=["last_activity_at"])
        transaction.on_commit(partial(notify_conversation, chat.pk))
    return call


def project_call(call: PhoneCall) -> None:
    """Update one generic activity card when the call's visible state changes."""
    from bloomerp.models.communication.instant_messaging import IMConversationActivity

    if not call.conversation_id or call.parent_call_id:
        return
    summary = _("Phone call: %(status)s · %(seconds)s seconds") % {
        "status": call.get_status_display(),
        "seconds": call.duration,
    }
    activity, created = IMConversationActivity.objects.get_or_create(
        conversation_id=call.conversation_id,
        kind="phone_call",
        source_id=str(call.pk),
        defaults={"summary": summary, "actor_id": call.handled_by_id},
    )
    if not created and activity.summary != summary:
        activity.summary = summary
        activity.save(update_fields=["summary", "datetime_updated"])
