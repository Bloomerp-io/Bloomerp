

from bloomerp.views.mixins.conditional_staff_required_mixin import ConditionalStaffRequiredMixin
from bloomerp.views.mixins.htmx_mixin import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

class BaseBloomerpView(
    ConditionalStaffRequiredMixin,
    LoginRequiredMixin,
    PermissionRequiredMixin,
    HtmxMixin,
):
    def has_permission(self):
        return True # Override in subclasses as needed