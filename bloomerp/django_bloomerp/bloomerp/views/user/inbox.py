from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from django.views.generic import TemplateView


@router.register(
    path="/inbox/",
    name="Inbox",
    description="View and manage your inbox messages.",
    url_name="inbox",
    route_type="app"
)
class InboxView(HtmxMixin, TemplateView):
    template_name = "user_views/inbox_view.html"
    