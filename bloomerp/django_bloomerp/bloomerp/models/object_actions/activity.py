from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_noop

from bloomerp.models.definition import ObjectAction
from bloomerp.models.object_actions.sidebar import sidebar_action


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
    )
