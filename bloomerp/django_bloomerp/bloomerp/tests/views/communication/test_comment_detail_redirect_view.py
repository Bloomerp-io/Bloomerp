from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.models.communication.comment import Comment
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpViewTestCase, ExpectedResult, RequestScenario


class TestCommentDetailRedirectView(BloomerpViewTestCase):
    """A comment link resolves its object only when the user may view it."""

    view_name = "comment_detail_redirect"

    def extendedSetup(self) -> None:
        """Create a comment on a real detail-view object."""
        self.todo = Todo.objects.create(title="Discuss launch")
        self.comment = Comment.objects.create(
            content="Please review",
            content_type=ContentType.objects.get_for_model(Todo),
            object_id=str(self.todo.pk),
            created_by=self.admin_user,
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover authorized redirect, missing comment, and hidden target."""
        return [
            RequestScenario(
                name="Comment link opens its target and selects comments",
                user=self.admin_user,
                view_kwargs={"comment_id": self.comment.pk},
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=self.redirect_has_comment_target,
                ),
            ),
            RequestScenario(
                name="Missing comment has no target",
                user=self.admin_user,
                view_kwargs={"comment_id": self.comment.pk + 100000},
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="User without target view access cannot follow comment",
                user=self.normal_user,
                view_kwargs={"comment_id": self.comment.pk},
                expected=ExpectedResult(status_code=404),
            ),
        ]

    def redirect_has_comment_target(self, response: HttpResponse) -> bool:
        """Check the redirected object, sidebar, and comment anchor."""
        detail_url = reverse("todos_detail_overview", kwargs={"pk": self.todo.pk})
        return self.comment.get_absolute_url() == reverse(
            "comment_detail_redirect", kwargs={"comment_id": self.comment.pk}
        ) and response["Location"] == (
            f"{detail_url}?sidebar=comments&comment={self.comment.pk}#comment-{self.comment.pk}"
        )
