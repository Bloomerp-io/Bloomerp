from django.views.generic import TemplateView

from bloomerp.models.workspaces.sql_query import SqlQuery
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView


@router.register(
    path="query/",
    name="Query",
    description="Query your data using SQL",
    route_type="model",
    url_name="query",
    models=[SqlQuery],
)
class SqlQueryView(BaseBloomerpView, TemplateView):
    """Display the full-width SQL query workspace."""
    model = SqlQuery
    template_name = "views/workspaces/sql_query.html"
    include_padding = False

    def has_permission(self) -> bool:
        """Require the existing SQL query creation and viewing permissions."""
        return UserPolicyManager(self.request.user).has_global_permission(
            SqlQuery,
            [BloomerpPermission.ADD, BloomerpPermission.VIEW]
        )
