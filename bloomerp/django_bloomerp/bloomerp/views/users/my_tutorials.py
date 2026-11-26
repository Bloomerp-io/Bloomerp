import json

from django.contrib.contenttypes.models import ContentType
from django.views.generic import TemplateView

from bloomerp.dataviews.card.config import CardDataView
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.tutorial import Tutorial
from bloomerp.models.tutorial.tutorial import STARTABLE_TUTORIAL
from bloomerp.modules.misc import MiscModule
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.router import router
from bloomerp.tokens import DataviewToken, RequestToken
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin

STARTABLE_TUTORIALS = FilterCondition(
    field_path="id", lookup_id=STARTABLE_TUTORIAL.id, value=True,
)


@router.register(
    path="my_tutorials/",
    name="My tutorials",
    description="Browse and start tutorials available to you.",
    route_type="module",
    url_name="my_tutorials",
    modules=[MiscModule],
)
class MyTutorialsView(BaseBloomerpView, DataviewMixin, TemplateView):
    """Show tutorials available to the signed-in learner."""

    def get_dataview_content_type_id(self) -> int:
        """Use Tutorial as the model for the shared cards."""
        return ContentType.objects.get_for_model(Tutorial).pk

    def get_dataview_request_token(self) -> RequestToken:
        """Configure tutorial cards and grant access to tutorials the viewer can start."""
        view = BloomerpPermission.VIEW
        eligible = Filter(connector="AND", conditions=[STARTABLE_TUTORIALS])
        return RequestToken(
            policies={Tutorial: AccessRule(
                row_permissions=[
                    RowPolicyRuleContent(permissions=[view], conditions=[STARTABLE_TUTORIALS]),
                ],
                field_permissions={"id": [view], "name": [view], "description": [view]},
            )},
            dataviews={Tutorial: DataviewToken(
                dataview=CardDataView(
                    display_fields=["description"],
                    default_filters={"filter": json.dumps([eligible.model_dump(mode="json")])},
                    item_click_action_id="start-tutorial",
                ),
                object_actions=["start-tutorial"],
                dataview_actions=[],
            )},
        )
