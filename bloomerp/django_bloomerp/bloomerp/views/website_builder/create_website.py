from bloomerp.models.access_control.row_policy import RowPolicyChoice
from registries.route_registry import router
from django.views.generic import TemplateView
from bloomerp.views.mixins import HtmxMixin
from django.db.models import Model
from typing import Any
from bloomerp.models import ApplicationField

@router.register(
    'create-website',
    'app',
)
class CreateWebsiteView(HtmxMixin, TemplateView):
    """
    A view that allows users to easily check what permissions
    certain users have without having to do fancy queries
    """
    include_padding = False
    template_name = "create_website.html"