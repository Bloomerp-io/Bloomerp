

from bloomerp.views.mixins.conditional_staff_required_mixin import ConditionalStaffRequiredMixin
from bloomerp.views.mixins.htmx_mixin import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

from bloomerp.views.mixins.message_mixin import MessageMixin

class BaseBloomerpView(
    LoginRequiredMixin,
    ConditionalStaffRequiredMixin,
    PermissionRequiredMixin,
    HtmxMixin,
    MessageMixin
):
    def has_permission(self):
        return True # Override in subclasses as needed