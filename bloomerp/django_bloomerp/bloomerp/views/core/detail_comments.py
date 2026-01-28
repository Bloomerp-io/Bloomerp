from django.contrib.auth.mixins import PermissionRequiredMixin
from bloomerp.models.communication import Comment
from .base_detail import BloomerpBaseDetailView
from registries.route_registry import router


@router.register(
    path="comments",
    name="Comments",
    url_name="{model}_detail_comments",
    description="Comments for object from {model} model",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailCommentsView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_comments_view.html"
    model = None

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self.object, "comments"):
            comments = Comment.objects.filter(content_type=self.content_type, object_id=self.object.pk)
        else:
            comments = self.object.comments.all()

        context["comments"] = comments
        return context
