from bloomerp.forms.auth import BloomerpUserCreationForm
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.models import model_name_plural_underline
from bloomerp.models.users.user import User
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.htmx_mixin import HtmxMixin


from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
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
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    model = None
    exclude = []
    success_message = "Object was created successfully."
    form_class = BloomerpUserCreationForm
    success_url = reverse_lazy("users_list")


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model"] = self.model
        return context

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def has_permission(self):
        manager = UserPermissionManager(self.request.user)

        return manager.has_global_permission(
            self.model,
            "add_user"
        )

    def get_success_message(self, cleaned_data):
        return f"User was created successfully."