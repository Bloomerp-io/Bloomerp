"""Full-page host for the existing streamed BloomAI conversation component."""

from typing import Any
from uuid import UUID

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from bloomerp.models.agents.ai_conversation import AIConversation
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="chat/", route_type="module", modules="bloomai",
    name="AI Chat", url_name="ai_chat",
)
@method_decorator(never_cache, name="dispatch")
class AIAgentView(BaseBloomerpView, TemplateView):
    """Display owner-scoped AI history alongside the shared agent composer."""

    template_name = "views/agents/ai_agent.html"
    htmx_include_addendum_padding = False

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Accept URL drafts only after checking ownership of the selected chat."""
        context = super().get_context_data(**kwargs)
        conversation_id = self.request.GET.get("conversation", "")
        if conversation_id:
            try:
                identifier = UUID(conversation_id)
            except ValueError as exc:
                raise Http404("Invalid conversation") from exc
            get_object_or_404(AIConversation, pk=identifier, owner=self.request.user)
        context.update(
            initial_conversation=conversation_id,
            initial_query=self.request.GET.get("query", ""),
        )
        return context
