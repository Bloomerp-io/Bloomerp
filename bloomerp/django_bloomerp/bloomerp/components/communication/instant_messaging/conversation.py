"""Reusable conversation fragment for the messaging orb and future Inbox hosts."""

from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.communication.builtins.instant_messaging.content import (
    render_message_html,
)
from bloomerp.communication.builtins.instant_messaging.controller import REACTION_EMOJIS
from bloomerp.communication.builtins.instant_messaging.presentation import (
    conversation_identity,
    participant_label,
)
from bloomerp.models.communication.instant_messaging import (
    IMConversationParticipant,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conversation/<uuid:conversation_id>",
    url_name="components_conversation",
)
@login_required
@require_GET
def conversation(request: HttpRequest, conversation_id: UUID) -> HttpResponse:
    """Render an authorized timeline or root thread, with a reusable text editor."""
    return render_conversation(request, conversation_id)


def render_conversation(request: HttpRequest, conversation_id: UUID) -> HttpResponse:
    """Render the same authorized fragment after either loading or creating a chat."""
    conversations = (
        IMAccessManager(request.user)
        .get_conversations()
        .select_related("connection")
        .prefetch_related(
            Prefetch(
                "participants",
                queryset=IMConversationParticipant.objects.select_related(
                    "user", "identity"
                ),
            )
        )
    )
    chat = get_object_or_404(conversations, pk=conversation_id)
    messages = (
        chat.messages.select_related("sender__user", "sender__identity", "reply_to")
        .prefetch_related("attachments", "reactions__participant")
        .annotate(reply_count=Count("thread_replies", distinct=True))
    )
    root = None
    if request.GET.get("thread"):
        try:
            root_id = UUID(request.GET["thread"])
        except ValueError:
            return HttpResponse(status=400)
        root = get_object_or_404(chat.messages, pk=root_id, thread_root__isnull=True)
        messages = messages.filter(Q(pk=root.pk) | Q(thread_root=root))
    else:
        messages = messages.filter(thread_root__isnull=True)
    rows = []
    for message in messages.order_by("sequence"):
        reactions: dict[str, dict[str, object]] = {}
        if not message.deleted_at:
            for reaction in message.reactions.all():
                item = reactions.setdefault(
                    reaction.emoji, {"emoji": reaction.emoji, "count": 0, "own": False}
                )
                item["count"] += 1
                if reaction.participant.user_id == request.user.pk:
                    item["own"] = True
        rows.append(
            {
                "message": message,
                "html": mark_safe(
                    render_message_html(message.body_html, request.user, chat)
                ),
                "own": message.sender.user_id == request.user.pk,
                "author": participant_label(message.sender),
                "reactions": list(reactions.values()),
                "reaction_emojis": REACTION_EMOJIS,
                "can_react": chat.provider_key == "internal"
                and chat.status != "archived"
                and not message.deleted_at,
            }
        )
    from bloomerp.utils.callables import resolve_hook
    from bloomerp.communication.builtins.instant_messaging.registry import (
        IM_PROVIDER_REGISTRY,
    )

    provider = IM_PROVIDER_REGISTRY.get(chat.provider_key)
    actions = {
        "can_send": chat.provider_key == "internal" and chat.status != "archived"
    }
    if provider and provider.actions_resolver:
        actions = resolve_hook(provider.actions_resolver)(request.user, chat)
    if provider and root is None:
        for source in provider.timeline_sources:
            for activity in resolve_hook(source.resolver)(request.user, chat):
                rows.append({"activity": activity, "template": source.template})
    rows.sort(key=timeline_order)
    from django.core import signing

    latest_activity = (
        chat.activities.order_by("-datetime_updated").first() if root is None else None
    )
    activity_token = (
        signing.dumps(
            {
                "conversation": str(chat.pk),
                "at": latest_activity.datetime_updated.isoformat(),
            },
            salt="im-activity-read",
        )
        if latest_activity
        else ""
    )
    response = render(
        request,
        (
            "components/communication/instant_messaging/messages.html"
            if request.GET.get("messages_only") == "1"
            else "components/communication/instant_messaging/conversation.html"
        ),
        {
            "conversation": chat,
            **actions,
            "identity": conversation_identity(chat, request.user.pk),
            "rows": rows,
            "activity_token": activity_token,
            "thread_root": root,
            "editor_name": f"im_body_{uuid4().hex}",
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response


def timeline_order(row: dict[str, object]) -> tuple[object, str]:
    """Order independent timeline records deterministically without duplicating calls."""
    record = row.get("message") or row["activity"]
    return getattr(record, "started_at", None) or record.datetime_created, str(
        record.pk
    )
