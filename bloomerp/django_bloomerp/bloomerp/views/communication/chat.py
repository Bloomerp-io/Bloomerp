"""Full-page host for the reusable staff messaging components."""

from typing import Any
from uuid import UUID

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="chat/", route_type="module", modules="communication",
    name="Chat", url_name="chat",
)
@method_decorator(never_cache, name="dispatch")
class ChatView(BaseBloomerpView, TemplateView):
    """Display member conversations beside their existing timeline and composer."""

    template_name = "views/communication/chat.html"
    htmx_include_addendum_padding = False

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Validate the selected conversation and pass URL state to the shared host."""
        context = super().get_context_data(**kwargs)
        conversation_id = self.request.GET.get("conversation", "")
        if conversation_id:
            try:
                identifier = UUID(conversation_id)
            except ValueError as exc:
                raise Http404("Invalid conversation") from exc
            get_object_or_404(
                IMAccessManager(self.request.user).get_conversations(), pk=identifier
            )
        context.update(
            initial_conversation=conversation_id,
            initial_query=self.request.GET.get("query", ""),
            initial_thread=self.request.GET.get("thread", ""),
            initial_search=self.request.GET.get("q", ""),
        )
        return context
