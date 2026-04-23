from __future__ import annotations

from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy

from bloomerp.auth import (
    allauth_is_enabled,
    get_interactive_auth_settings,
    get_login_field_label,
    get_login_help_text,
    get_social_login_providers,
)
from bloomerp.forms.auth import BloomerpAuthenticationForm


class BloomerpLoginView(LoginView):
    authentication_form = BloomerpAuthenticationForm
    template_name = "auth_views/login_view.html"
    next_page = reverse_lazy("bloomerp_home_view")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interactive_auth = get_interactive_auth_settings()
        social_providers = get_social_login_providers()
        context.update(
            {
                "interactive_auth": interactive_auth,
                "login_field_label": get_login_field_label(),
                "login_help_text": get_login_help_text(),
                "social_login_providers": social_providers,
                "social_login_enabled": bool(social_providers),
                "social_login_runtime_ready": allauth_is_enabled(),
            }
        )
        return context
