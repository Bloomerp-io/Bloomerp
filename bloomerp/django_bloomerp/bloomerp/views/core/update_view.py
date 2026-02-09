from typing import Any
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.generic.edit import UpdateView
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from bloomerp.models.files import File
from bloomerp.models.workspaces import Widget
from bloomerp.utils.models import get_detail_view_url, get_list_view_url
from bloomerp.views.mixins import BloomerpModelFormViewMixin, BloomerpModelContextMixin, HtmxMixin
from bloomerp.router import router


@router.register(
    path="update",
    name="Update",
    url_name="update",
    description="Update object from {model}",
    route_type="detail",
    exclude_models=[File, Widget],
)
class BloomerpUpdateView(
    PermissionRequiredMixin,
    SuccessMessageMixin,
    HtmxMixin,
    BloomerpModelFormViewMixin,
    BloomerpModelContextMixin,
    UpdateView,
):
    template_name = "detail_views/bloomerp_detail_update_view.html"
    settings = None
    _uses_base_form = False
    module = None
    
    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})

    def get_permissions(self):
        """
        Returns a dictionary of standard add, change, delete, and view permissions
        for the given model.

        Returns:
        Dictionary with keys 'add', 'change', 'delete', 'view' and their corresponding
        permission codenames as values.
        """
        model_name = self.model._meta.model_name
        app_label = self.model._meta.app_label

        permissions = {
            "create": f"{app_label}.add_{model_name}",
            "update": f"{app_label}.change_{model_name}",
            "delete": f"{app_label}.delete_{model_name}",
            "read": f"{app_label}.view_{model_name}",
        }

        return permissions

    def get_permission_required(self):
        return [self.get_permissions()["update"]]

    def post(self, request: HttpRequest, *args: str, **kwargs: Any) -> HttpResponse:
        if request.POST.get("delete"):
            if not request.user.has_perm(self.get_permissions()["delete"]):
                messages.error(
                    request,
                    f"User does not have the required permission: {self.get_permissions()['delete']}.",
                )
                return HttpResponseRedirect(request.path)

            self.get_object().delete()
            messages.info(request, "Object was deleted successfully.")

            url = get_list_view_url(self.model)

            return HttpResponseRedirect(reverse(url))

        return super().post(request, *args, **kwargs)

    def get_success_message(self, cleaned_data):
        return f"{self.object} was updated successfully."
