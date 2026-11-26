import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect, HttpResponseLocation

from bloomerp.models.files import FileNode
from bloomerp.models.workspaces import SqlQuery, Tile
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.labels import safe_object_label
from bloomerp.utils.models import get_delete_view_url, get_list_view_url
from bloomerp.utils.navigation import supports_main_content_navigation
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView

User = get_user_model()
logger = logging.getLogger(__name__)

# TODO: messaging using messages api does not show up...


@router.register(
    path="delete",
    name="Delete",
    url_name="delete",
    description="Delete an object from {model}",
    route_type="detail",
    exclude_models=[FileNode,],
)
class BloomerpDeleteView(BaseBloomerpDetailView):
    template_name = "views/generic/detail/delete.html"


    def get_object(self, queryset=None):
        if getattr(self, "object", None) is None:
            self.object = super().get_object(queryset=queryset)
        return self.object

    def get_delete_preview(self) -> dict:
        if not hasattr(self, "_delete_preview"):
            self._delete_preview = _build_delete_preview(self.get_object())
        return self._delete_preview

    def has_permission(self):
        permission_manager = UserPolicyManager(self.request.user)

        return (
            permission_manager.has_global_permission(self.model, BloomerpPermission.DELETE)
            and permission_manager.has_access_to_object(self.get_object(), BloomerpPermission.DELETE)
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare the deletion summary and the confirmation form's destination."""
        context = super().get_context_data(**kwargs)
        delete_preview = self.get_delete_preview()
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["related_objects"] = delete_preview["related_objects"]
        context["protected_objects"] = delete_preview["protected_objects"]
        context["total_objects"] = delete_preview["total_objects"]
        context["list_url"] = self.get_success_url()
        context["delete_submit_url"] = self.get_delete_submit_url()
        context["delete_submit_target"] = (
            f"#{self.htmx_main_target}" if self.get_htmx_include_addendum() else ""
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Delete the confirmed object and return to its model list."""
        self.object = self.get_object()
        delete_preview = self.get_delete_preview()
        try:
            self.pre_delete_detail_url = self.object.get_absolute_url()
        except Exception:
            self.pre_delete_detail_url = ""
        if delete_preview["protected_objects"]:
            context = self.get_context_data(object=self.object)
            return self.handle_conflict_response(context)

        deleted_count, deleted_by_model = self.object.delete()
        logger.info(
            "Deleted %s object(s) for %s.%s pk=%s: %s",
            deleted_count,
            self.model._meta.app_label,
            self.model.__name__,
            self.kwargs.get("pk"),
            deleted_by_model,
        )
        messages.success(self.request, "Object was deleted successfully.")
        return self.handle_success_response()

    def get_success_url(self):
        return reverse(get_list_view_url(self.model))

    def get_delete_submit_url(self):
        return reverse(get_delete_view_url(self.model), kwargs={"pk": self.object.pk})

    def handle_conflict_response(self, context: dict[str, Any]) -> HttpResponse:
        """Show the current confirmation when a page submission can no longer delete."""
        if (
            context["delete_submit_target"]
            and getattr(self.request.htmx, "target", None) == self.htmx_main_target
        ):
            return HttpResponseLocation(
                context["delete_submit_url"],
                target=context["delete_submit_target"],
                status=409,
            )
        return self.render_to_response(context, status=409)

    def handle_success_response(self) -> HttpResponse:
        """Load the model list into the main content region for HTMX submissions."""
        success_url = self.get_success_url()
        if self.request.htmx:
            if supports_main_content_navigation(success_url):
                return HttpResponseLocation(success_url, target=f"#{self.htmx_main_target}")
            return HttpResponseClientRedirect(success_url)
        return redirect(success_url)


def _build_delete_preview(obj) -> dict:
    collector = Collector(using=obj._state.db)
    protected_objects = []

    try:
        collector.collect([obj])
    except (ProtectedError, RestrictedError) as exc:
        protected_objects = [safe_object_label(item) for item in exc.protected_objects]

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
                "objects": [safe_object_label(instance) for instance in filtered_instances[:5]],
            }
        )

    return {
        "related_objects": related_objects,
        "protected_objects": protected_objects,
        "total_objects": total_objects,
    }
