"""Group membership controls shared by inbox and orb conversation headers."""

import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.router import router


@router.register(
    path="components/communication/im/groups/<uuid:conversation_id>/members/",
    url_name="components_im_group_members",
)
@login_required
@require_http_methods(["GET", "POST", "PATCH"])
def group_members(request: HttpRequest, conversation_id: UUID) -> HttpResponse:
    """Render members and authorize form mutations or SDK group-name patches."""
    chat = get_object_or_404(
        IMAccessManager(request.user).get_conversations(),
        pk=conversation_id,
        kind="group",
        connection__isnull=True,
    )
    controller = IMController(request.user)
    if request.method == "PATCH":
        try:
            payload = json.loads(request.body)
            if not isinstance(payload, dict) or set(payload) != {"name"} or not isinstance(payload["name"], str):
                return JsonResponse({"error": "Provide a group name."}, status=400)
            chat = controller.update_internal_group(chat.pk, "rename", name=payload["name"])
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
        except ValidationError as exc:
            return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
        response = JsonResponse({"id": str(chat.pk), "name": chat.name})
        response["Cache-Control"] = "private, no-store"
        return response
    error = None
    if request.method == "POST":
        try:
            chat = controller.update_internal_group(
                chat.pk,
                request.POST.get("action", ""),
                user_id=request.POST.get("user_id", ""),
                name=request.POST.get("name", ""),
            )
        except (ValueError, ValidationError) as exc:
            error = (
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Invalid participant."
            )
        else:
            if request.POST.get("action") == "leave":
                response = HttpResponse("You have left this group.")
                response["HX-Retarget"] = "closest .im-conversation-content"
                response["HX-Reswap"] = "outerHTML"
                response["HX-Trigger"] = "im:unread-changed"
                return response
    member = chat.participants.get(user=request.user, left_at__isnull=True)
    query = request.GET.get("recipient_query", "")[:200]
    try:
        page = (
            controller.discover_recipients(query, request.GET.get("cursor"))
            if member.role in {"owner", "admin"}
            else None
        )
    except ValueError:
        return HttpResponse(status=400)
    response = render(
        request,
        "components/communication/instant_messaging/group_members.html",
        {
            "conversation": chat,
            "member": member,
            "members": chat.participants.filter(left_at__isnull=True).select_related(
                "user"
            ),
            "can_manage": member.role in {"owner", "admin"},
            "page": page,
            "query": query,
            "error": error,
        },
    )
    response["Cache-Control"] = "private, no-store"
    if request.method == "POST" and not error:
        response["HX-Trigger"] = json.dumps({"im:unread-changed": {}})
    return response
