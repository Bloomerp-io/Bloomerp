from bloomerp.forms.auth import BloomerpUserCreationForm
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.base import BaseBloomerpView

from django.contrib.auth import get_user_model
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views.generic.edit import FormView


User = get_user_model()


@router.register(
    path="create",
    name="Create user",
    url_name="add",
    description="Create a new object from User",
    route_type="model",
    models=User
)
class UserCreateView(BaseBloomerpView, SuccessMessageMixin, FormView):
    template_name = "views/users/create.html"
    fields = None
    model = User
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
        return reverse(get_detail_view_url(self.model), kwargs={"pk": self.object.pk})

    def has_permission(self):
        manager = UserPolicyManager(self.request.user)

        return manager.has_global_permission(
            self.model,
            BloomerpPermission.ADD
        )

    def get_success_message(self, cleaned_data):
        return "User was created successfully."
