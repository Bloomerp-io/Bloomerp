from django.urls import reverse
from django.utils.translation import gettext_noop

from bloomerp.models.actions.object.sidebar import sidebar_action
from bloomerp.models.definition import ObjectAction


def comments_action() -> ObjectAction:
    """Open a record's comments in its detail sidebar."""
    return sidebar_action(
        id="comments",
        label=gettext_noop("Comments"),
        icon="fa fa-comments",
        endpoint=lambda context: reverse("components_comments", kwargs={
            "content_type_id": context.content_type.pk,
            "object_id": context.object.pk,
        }),
        remembered_view="comments",
        shortcut="d then m"
    )
