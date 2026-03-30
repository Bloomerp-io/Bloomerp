from bloomerp.models.communication import Comment
from .base_detail import BloomerpBaseDetailView
from bloomerp.router import router


@router.register(
    path="comments",
    name="Comments",
    url_name="{model}_detail_comments",
    description="Comments for object from {model} model",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailCommentsView(BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_comments_view.html"
    model = None
    

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self.object, "comments"):
            comments = Comment.objects.filter(content_type=self.content_type, object_id=self.object.pk)
        else:
            comments = self.object.comments.all()

        context["comments"] = comments
        return context
