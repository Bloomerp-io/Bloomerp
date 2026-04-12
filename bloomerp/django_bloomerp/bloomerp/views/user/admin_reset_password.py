from bloomerp.router import router
from bloomerp.models.users.user import User
from bloomerp.views.core import BloomerpBaseDetailView


from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.generic.edit import FormView


@router.register(
    path='reset-password/',
    models=[User],
    route_type='detail',
    name='Reset password for user',
    url_name='reset_password_for_user',
    description='Reset password for a user'
)
class UserAdminPasswordResetView(UserPassesTestMixin, BloomerpBaseDetailView, FormView):
    template_name = 'auth_views/profile_password_reset.html'
    form_class = AdminPasswordChangeForm

    def test_func(self):
        return self.request.user.is_superuser

    def get_success_url(self):
        return self.get_object().get_absolute_url()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.get_object()
        return kwargs

    def form_valid(self, form:AdminPasswordChangeForm):
        self.object = self.get_object()
        form.save()
        return super().form_valid(form)

    def form_invalid(self, form):
        self.object = self.get_object()
        return super().form_invalid(form)