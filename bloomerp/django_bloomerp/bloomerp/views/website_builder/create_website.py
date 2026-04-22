from bloomerp.router import router
from django.views.generic import TemplateView
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.htmx_mixin import HtmxMixin

@router.register(
    'create-website',
    'app',
)
class CreateWebsiteView(BaseBloomerpView, TemplateView):
    """
    A view that allows users to easily check what permissions
    certain users have without having to do fancy queries
    """
    include_padding = False
    template_name = "create_website.html"