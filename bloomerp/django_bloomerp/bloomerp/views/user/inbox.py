from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.htmx_mixin import HtmxMixin
from django.views.generic import TemplateView


@router.register(
    path="/inbox/",
    name="Inbox",
    description="View and manage your inbox messages.",
    url_name="inbox",
    route_type="app"
)
class InboxView(BaseBloomerpView, TemplateView):
    template_name = "user_views/inbox_view.html"
    