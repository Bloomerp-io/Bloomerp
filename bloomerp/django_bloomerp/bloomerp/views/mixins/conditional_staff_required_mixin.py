from django.conf import settings
from django.template.response import TemplateResponse
from django.urls import reverse_lazy

from bloomerp.auth import get_bloomerp_config


class ConditionalStaffRequiredMixin:
    """
    Mixin to ensure that only staff members can access the view.
    """
    staff_only_template_name = "403.html"
    staff_only_partial_template_name = "snippets/403.html"
    staff_only_title = "Staff Access Required"
    staff_only_message = "This page is only available to staff members."

    def staff_access_required(self) -> bool:
        config = get_bloomerp_config()
        interactive_auth = config.auth.interactive
        return bool(
            config.require_staff_for_access and not interactive_auth.allow_non_staff_bloomerp_access
        )

    def get_staff_only_template_name(self, request) -> str:
        if request.headers.get("HX-Request"):
            return self.staff_only_partial_template_name
        return self.staff_only_template_name

    def render_staff_only_response(self, request):
        is_authenticated = bool(getattr(request.user, "is_authenticated", False))
        return TemplateResponse(
            request,
            self.get_staff_only_template_name(request),
            {
                "title": self.staff_only_title,
                "message": (
                    "You are signed in, but this page is only available to staff members."
                    if is_authenticated
                    else self.staff_only_message
                ),
                "login_url": getattr(settings, "LOGIN_URL", None) or reverse_lazy("login"),
                "logout_url": getattr(settings, "LOGOUT_URL", None) or reverse_lazy("logout"),
                "is_authenticated": is_authenticated,
            },
            status=403,
        )

    def dispatch(self, request, *args, **kwargs):
        if self.staff_access_required() and not getattr(request.user, "is_staff", False):
            return self.render_staff_only_response(request)

        return super().dispatch(request, *args, **kwargs)
