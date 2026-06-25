from bloomerp.forms.auth import BloomerpUserCreationForm
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.models.users.user import User
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.base import BaseBloomerpView

from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views.generic.edit import FormView


@router.register(
    path="create",
    name="Create user",
    url_name="add",
    description="Create a new object from User",
    route_type="model",
    models=User
)
class UserCreateView(BaseBloomerpView, SuccessMessageMixin, FormView):
    template_name = "views/generic/detail/create.html"
    fields = None
    model = None
    exclude = []
    success_message = "Object was created successfully."
    form_class = BloomerpUserCreationForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model"] = self.model
        return context

    def form_valid(self, form):
        self.object = form.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(get_detail_view_url(User), kwargs={"pk": self.object.pk})

    def has_permission(self):
        manager = UserPermissionManager(self.request.user)

        return manager.has_global_permission(
            self.model,
            "add_user"
        )

    def get_success_message(self, cleaned_data):
        return f"User was created successfully."
