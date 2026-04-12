"""
A view that shows which users have access to the particular object.
"""

from bloomerp.router import router
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView
from django.contrib.auth.mixins import PermissionRequiredMixin

# @router.register(
#     path = "access-control",
#     route_type = "detail",
#     name="Access Control",
#     description="Check which objects have access to this particular object",
#     models="__all__"
# )
# class BloomerpDetailOverviewView(BloomerpBaseDetailView):
#     template_name = "detail_views/bloomerp_detail_access_control_view.html"

