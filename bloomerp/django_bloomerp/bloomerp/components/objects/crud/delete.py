from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.router import router
from bloomerp.models.definition import apply_model_base_filter
from bloomerp.views.generic.detail.delete import BloomerpDeleteView


# TODO: integrate with crud components

# TODO: Add tests for delete view

@router.register(
    path="components/delete-object/<int:content_type_id>/<str:object_id>/",
    name="components_delete_object",
)
class DeleteObjectComponentView(BloomerpDeleteView):
    htmx_include_addendum = False

    def dispatch(self, request, *args, **kwargs):
        self.content_type = get_object_or_404(ContentType, id=kwargs["content_type_id"])
        self.model = self.content_type.model_class()
        if self.model is None:
            return HttpResponse("Invalid content type", status=400)
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset: QuerySet[Model] | None = None) -> Model:
        """Resolve modal deletions through the same base filter as detail views."""
        queryset = (
            self.get_queryset()
            if queryset is None
            else apply_model_base_filter(queryset)
        )
        return get_object_or_404(queryset, id=self.kwargs["object_id"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["content_type_id"] = self.content_type.pk
        return context

    def get_delete_submit_url(self):
        return reverse(
            "components_delete_object",
            kwargs={
                "content_type_id": self.content_type.pk,
                "object_id": self.object.pk,
            },
        )

    def handle_success_response(self):
        if not self.request.htmx:
            return super().handle_success_response()

        current_url = self.request.headers.get("HX-Current-URL", "")
        detail_url = getattr(self, "pre_delete_detail_url", "")

        response = HttpResponse(status=204)
        if current_url.rstrip("/") == detail_url.rstrip("/"):
            response["HX-Redirect"] = self.get_success_url()
        else:
            response["HX-Refresh"] = "true"
        return response
