"""Full-size Pages editor, replacing the generated Page collection view."""

from typing import Any

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from bloomerp.models import Page
from bloomerp.router import router
from bloomerp.services.page_services import page_context
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="/",
    name="Pages",
    route_type="model",
    models=[Page],
    url_name="model",
    override=True,
)
@method_decorator(never_cache, name="dispatch")
class BloomerpPagesView(BaseBloomerpView, TemplateView):
    """Render saved pages in the existing editor and resizable navigation layout."""

    template_name = "views/pages.html"
    htmx_include_addendum_padding = False
    model = None
    module = None
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Load only owned or explicitly shared pages into the editor."""
        return {**super().get_context_data(**kwargs), **page_context(self.request)}
