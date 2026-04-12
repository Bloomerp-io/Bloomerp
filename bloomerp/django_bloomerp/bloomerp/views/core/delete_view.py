from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.db.models.deletion import Collector
from django.db.models.deletion import ProtectedError
from django.db.models.deletion import RestrictedError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from bloomerp.models.files import File
from bloomerp.models.workspaces import SqlQuery, Tile
from bloomerp.router import router
from bloomerp.utils.models import get_delete_view_url
from bloomerp.utils.models import get_list_view_url
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView


User = get_user_model()

# TODO: messaging using messages api does not show up...

@router.register(
    path="delete",
    name="Delete {model}",
    url_name="delete",
    description="Delete an object from {model}",
    route_type="detail",
    exclude_models=[File, Tile, SqlQuery, User],
)
class BloomerpDeleteView(BloomerpBaseDetailView):
    template_name = "delete_views/bloomerp_delete_view.html"
    permissions = ["delete"]

    def get_object(self, queryset=None):
        if getattr(self, "object", None) is None:
            self.object = super().get_object(queryset=queryset)
        return self.object

    def get_delete_preview(self) -> dict:
        if not hasattr(self, "_delete_preview"):
            self._delete_preview = _build_delete_preview(self.get_object())
        return self._delete_preview

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        delete_preview = self.get_delete_preview()
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["related_objects"] = delete_preview["related_objects"]
        context["protected_objects"] = delete_preview["protected_objects"]
        context["total_objects"] = delete_preview["total_objects"]
        context["list_url"] = self.get_success_url()
        context["delete_submit_url"] = self.get_delete_submit_url()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        delete_preview = self.get_delete_preview()
        try:
            self.pre_delete_detail_url = self.object.get_absolute_url()
        except Exception:
            self.pre_delete_detail_url = ""
        if delete_preview["protected_objects"]:
            context = self.get_context_data(object=self.object)
            return self.render_to_response(context, status=409)

        self.object.delete()
        messages.success(self.request, "Object was created successfully.")
        return self.handle_success_response()

    def get_success_url(self):
        return reverse(get_list_view_url(self.model))

    def get_delete_submit_url(self):
        return reverse(get_delete_view_url(self.model), kwargs={"pk": self.object.pk})

    def handle_success_response(self):
        success_url = self.get_success_url()
        if self.request.htmx:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = success_url
            return response
        return redirect(success_url)


def _build_delete_preview(obj) -> dict:
    collector = Collector(using=obj._state.db)
    protected_objects = []

    try:
        collector.collect([obj])
    except (ProtectedError, RestrictedError) as exc:
        protected_objects = [str(item) for item in exc.protected_objects]

    related_objects = []
    total_objects = 1

    for model, instances in collector.data.items():
        instance_list = list(instances)
        filtered_instances = [
            instance for instance in instance_list
            if not (model == obj.__class__ and instance.pk == obj.pk)
        ]
        if not filtered_instances:
            continue

        total_objects += len(filtered_instances)
        related_objects.append(
            {
                "model_name": model._meta.verbose_name_plural.title(),
                "count": len(filtered_instances),
                "objects": [str(instance) for instance in filtered_instances[:5]],
            }
        )

    return {
        "related_objects": related_objects,
        "protected_objects": protected_objects,
        "total_objects": total_objects,
    }
