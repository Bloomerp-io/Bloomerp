from django.contrib.contenttypes.models import ContentType
from django.views.generic import TemplateView

from bloomerp.dataviews.card.config import CardDataView
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.parser import serialize_filter_query_params
from bloomerp.models.workspaces.workspace import (
    AVAILABLE_WORKSPACE,
    CREATE_WORKSPACE,
    OPEN_WORKSPACE,
    Workspace,
)
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.router import router
from bloomerp.tokens import DataviewToken, RequestToken
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin

AVAILABLE_WORKSPACE_CONDITION = FilterCondition(
    field_path="id", lookup_id=AVAILABLE_WORKSPACE.id, value=True,
)
WORKSPACE_FILTERS = serialize_filter_query_params([
    Filter(connector="AND", conditions=[AVAILABLE_WORKSPACE_CONDITION]),
])


@router.register(
    path="workspaces/",
    url_name="my_workspaces",
    route_type="app",
    name="My workspaces",
    description="List of your workspaces",
)
class MyWorkspacesView(BaseBloomerpView, DataviewMixin, TemplateView):
    """Show the current user's owned and shared workspaces as cards."""

    dataview_hide_filters = True

    def get_dataview_content_type_id(self) -> int:
        """Use Workspace as the shared dataview's model."""
        return ContentType.objects.get_for_model(Workspace).pk

    def get_dataview_request_token(self) -> RequestToken:
        """Configure workspace cards and grant access to the viewer's available workspaces."""
        view = BloomerpPermission.VIEW
        return RequestToken(
            policies={Workspace: AccessRule(
                row_permissions=[RowPolicyRuleContent(
                    permissions=[view], conditions=[AVAILABLE_WORKSPACE_CONDITION],
                )],
                field_permissions={"module_id": [view]},
            )},
            dataviews={Workspace: DataviewToken(
                dataview=CardDataView(display_fields=["module_id"], default_filters=WORKSPACE_FILTERS),
                object_actions=[OPEN_WORKSPACE.id],
                dataview_actions=[CREATE_WORKSPACE.id],
            )},
        )
