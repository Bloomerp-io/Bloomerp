"""
A view that shows which users have access to the particular object.
"""

from bloomerp.router import router
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from django.contrib.auth.mixins import PermissionRequiredMixin

# @router.register(
#     path = "access-control",
#     route_type = "detail",
#     name="Access Control",
#     description="Check which objects have access to this particular object",
#     models="__all__"
# )
# class BloomerpDetailOverviewView(BaseBloomerpDetailView):
#     template_name = "views/generic/detail/access_control.html"

