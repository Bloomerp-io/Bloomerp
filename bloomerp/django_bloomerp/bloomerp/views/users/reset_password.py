from bloomerp.router import router
from bloomerp.models.users.user import User
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView


from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import AdminPasswordChangeForm, PasswordChangeForm
from django.urls import reverse_lazy
from django.views.generic.edit import FormView


@router.register(
    path="reset-password/",
    models=User,
    route_type="detail",
    name="Reset password",
    description="Reset password for a user",
    url_name="reset_password"
)
class BloomerpProfilePasswordResetView(BaseBloomerpDetailView, FormView):
    template_name = 'views/users/password_reset.html'
    form_class = PasswordChangeForm
    success_url = reverse_lazy('users_my_profile_overview')
    model = None

    def get_form_class(self):
        if self.request.user.is_superuser and self.get_object() is not self.request.user:
            return AdminPasswordChangeForm
        return PasswordChangeForm

    def has_permission(self):
        if self.get_object() is self.request.user:
            return True
        return self.request.user.is_superuser
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.get_object()
        return kwargs

    def form_valid(self, form: PasswordChangeForm | AdminPasswordChangeForm):
        self.object = self.get_object()
        form.save()
        if form.user is self.request.user:
            update_session_auth_hash(self.request, form.user)
        return super().form_valid(form)

    def form_invalid(self, form):
        self.object = self.get_object()
        return super().form_invalid(form)