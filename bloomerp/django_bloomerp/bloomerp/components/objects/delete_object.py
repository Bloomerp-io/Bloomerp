from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.router import router
from bloomerp.views.detail.delete_view import BloomerpDeleteView


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

    def get_object(self, queryset=None):
        return get_object_or_404(self.model, id=self.kwargs["object_id"])

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
