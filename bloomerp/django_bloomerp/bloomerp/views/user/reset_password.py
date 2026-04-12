from bloomerp.router import router
from bloomerp.models.users.user import User
from bloomerp.views.core import BloomerpBaseDetailView


from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.urls import reverse_lazy
from django.views.generic.edit import FormView

from bloomerp.views.user.base import ProfileMixin


@router.register(
    path="my-profile/reset-password/",
    models=User,
    route_type="model",
    name="Reset password",
    description="Reset password for a user",
    url_name="my_profile_change_password"
)
class BloomerpProfilePasswordResetView(ProfileMixin, BloomerpBaseDetailView, FormView):
    template_name = 'auth_views/profile_password_reset.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('users_my_profile_overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form:PasswordChangeForm):
        self.object = self.get_object()
        form.save()
        update_session_auth_hash(self.request, form.user)  # Prevents logout
        return super().form_valid(form)

    def form_invalid(self, form):
        self.object = self.get_object()
        return super().form_invalid(form)