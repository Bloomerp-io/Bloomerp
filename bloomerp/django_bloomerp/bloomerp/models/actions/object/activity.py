from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_noop

from bloomerp.models.actions.object.sidebar import sidebar_action
from bloomerp.models.definition import ObjectAction


def activity_action() -> ObjectAction:
    """Open a record's activity log in its detail sidebar."""
    return sidebar_action(
        id="activity",
        label=gettext_noop("Activity"),
        icon="fa fa-history",
        endpoint=lambda context: reverse("components_activity_log") + "?" + urlencode({
            "content_type_id": context.content_type.pk,
            "object_id": context.object.pk,
        }),
        remembered_view="activity",
        shortcut="d then a"
    )
