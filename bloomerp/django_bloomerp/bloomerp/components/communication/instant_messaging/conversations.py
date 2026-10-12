"""Accessible conversation search for the floating messaging panel."""

from django.contrib.auth.decorators import login_required
from django.db.models import BigIntegerField, Count, F, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.communication.builtins.instant_messaging.presentation import (
    conversation_identity,
)
from bloomerp.models.communication.instant_messaging import (
    IMConversationParticipant,
    IMMessage,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conversations/",
    url_name="components_im_conversations",
)
@login_required
@require_GET
def conversations(request: HttpRequest) -> HttpResponse:
    """Search only member conversations and return links to their reusable fragments."""
    queryset = (
        IMAccessManager(request.user)
        .get_conversations()
        .select_related("connection")
        .prefetch_related(
            Prefetch(
                "participants",
                queryset=IMConversationParticipant.objects.select_related(
                    "user", "identity", "last_read_message"
                ),
            )
        )
    )
    query = request.GET.get("q", "").strip()[:200]
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(participants__user__username__icontains=query)
            | Q(participants__user__first_name__icontains=query)
            | Q(participants__user__last_name__icontains=query)
            | Q(participants__user__email__icontains=query)
            | Q(participants__identity__display_name__icontains=query)
            | Q(participants__identity__address__icontains=query)
            | Q(messages__body__icontains=query, messages__deleted_at__isnull=True)
        ).distinct()
    read_sequence = IMConversationParticipant.objects.filter(
        conversation_id=OuterRef("conversation_id"),
        user=request.user,
        left_at__isnull=True,
    ).values("last_read_message__sequence")[:1]
    unread_messages = (
        IMMessage.objects.filter(
            conversation__in=IMAccessManager(request.user).get_conversations(),
            thread_root__isnull=True,
            deleted_at__isnull=True,
        )
        .exclude(sender__user=request.user)
        .annotate(
            read_sequence=Coalesce(
                Subquery(read_sequence), 0, output_field=BigIntegerField()
            )
        )
        .filter(sequence__gt=F("read_sequence"))
    )
    unread_counts = (
        unread_messages.filter(conversation_id=OuterRef("pk"))
        .order_by()
        .values("conversation_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    queryset = queryset.annotate(
        unread_count=Coalesce(
            Subquery(unread_counts), 0, output_field=BigIntegerField()
        )
    )
    if request.GET.get("unread"):
        queryset = queryset.filter(unread_count__gt=0)
    rows = []
    for chat in queryset[:100]:
        rows.append(
            {
                "conversation": chat,
                "identity": conversation_identity(chat, request.user.pk),
                "latest": chat.messages.order_by("-sequence").first(),
                "unread": chat.unread_count,
            }
        )
    unread_total = unread_messages.count()
    response = render(
        request,
        "components/communication/instant_messaging/conversations.html",
        {"rows": rows, "unread_total": unread_total},
    )
    response["Cache-Control"] = "private, no-store"
    return response
