from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import NoReverseMatch, reverse

from bloomerp.models.communication.comment import Comment
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.models import get_detail_view_url


@router.register(
    path="/comments/<int:comment_id>/",
    route_type="app",
    url_name="comment_detail_redirect",
    name="Comment detail redirect",
)
def comment_detail_redirect(request: HttpRequest, comment_id: int) -> HttpResponse:
    """Open a comment's related object with its Comments sidebar selected."""
    comment = get_object_or_404(Comment, pk=comment_id)
    related_object = comment.content_object
    if related_object is None or not UserPolicyManager(request.user).has_access_to_object(
        related_object, BloomerpPermission.VIEW
    ):
        raise Http404("Comment or related object not found")

    try:
        detail_url = reverse(get_detail_view_url(type(related_object)), kwargs={"pk": related_object.pk})
    except NoReverseMatch as exc:
        raise Http404("Related object has no detail view") from exc
    return redirect(f"{detail_url}?sidebar=comments&comment={comment.pk}#comment-{comment.pk}")
