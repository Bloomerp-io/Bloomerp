from bloomerp.router import router
from bloomerp.models.users.user import User
from bloomerp.views.mixins import BloomerpModelContextMixin, BloomerpModelFormViewMixin, HtmxMixin


from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic.edit import UpdateView


from typing import Any

from bloomerp.views.user.base import ProfileMixin


@router.register(
    path="my-profile/",
    models=User,
    route_type="model",
    name="Profile",
    description="Overview of profile",
    url_name="my_profile_overview"
)
class BloomerpProfileView(BloomerpModelFormViewMixin, ProfileMixin, HtmxMixin, BloomerpModelContextMixin, UpdateView):
    template_name = 'auth_views/profile_overview.html'
    fields = ['first_name', 'last_name', 'date_view_preference', 'datetime_view_preference', 'avatar']
    success_url = reverse_lazy('users_my_profile_overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.request.user
        return kwargs

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = self.get_form()
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect(self.success_url)
        else:
            return self.form_invalid(form)