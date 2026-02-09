from django.urls import reverse
from django.views.generic.edit import CreateView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth import get_user_model
from django.contrib.messages.views import SuccessMessageMixin
from bloomerp.models.files import File
from bloomerp.models.workspaces import Widget, SqlQuery
from bloomerp.utils.models import model_name_plural_underline, get_detail_view_url
from bloomerp.views.mixins import BloomerpModelFormViewMixin, HtmxMixin
from bloomerp.router import router


User = get_user_model()


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    exclude_models=[File, Widget, SqlQuery, User],
)
class BloomerpCreateView(
    PermissionRequiredMixin,
    SuccessMessageMixin,
    HtmxMixin,
    BloomerpModelFormViewMixin,
    CreateView,
):
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    exclude = []
    success_message = "Object was created successfully."
    module = None
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["list_view_url"] = model_name_plural_underline(self.model) + "_list"
        context["model"] = self.model
        context["title"] = "Create " + self.model._meta.verbose_name
        return context

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"]

    def get_success_message(self, cleaned_data):
        return f"{self.object} was created successfully."

    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})
