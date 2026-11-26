from typing import Any, ClassVar

from django.views.generic.base import ContextMixin

from bloomerp.filters.definition import Filters
from bloomerp.filters.parser import serialize_filter_query_params
from bloomerp.tokens import (
    DataviewToken,
    PermissionToken,
    RequestToken,
    get_token,
    issue_token,
    request_token_id,
)


class DataviewMixin(ContextMixin):
    """Provide a shared loader with typed filters and a request context."""

    dataview_template_name = "mixins/dataview_mixin.html"
    template_name = dataview_template_name
    filters: ClassVar[Filters] = []
    args: ClassVar[dict[str, str]] = {}
    dataview_content_type_id: int | None = None
    dataview_hide_filters = False
    dataview_sync_url = False
    dataview_filter_shorthand = False

    def get_dataview_filters(self) -> Filters:
        """Return the filter groups applied to the dataview."""
        return self.filters

    def get_dataview_args(self) -> dict[str, str]:
        """Return arguments passed to the dataview frontend."""
        return self.args

    def get_dataview_content_type_id(self) -> int | None:
        """Return the content type rendered by the loader."""
        return self.dataview_content_type_id

    def get_dataview_query_params(self) -> dict[str, str]:
        """Return additional controls consumed by the dataview renderer."""
        return {}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Include the dataview loader in the surrounding view context."""
        return {**super().get_context_data(**kwargs), **self.get_dataview_context()}

    def get_dataview_context(self) -> dict[str, Any]:
        """Build the loader fragment and attach its request context."""
        query_params = self.get_dataview_query_params()
        query_params.update(
            serialize_filter_query_params(
                self.get_dataview_filters(), shorthand=self.dataview_filter_shorthand
            )
        )

        ctx: dict[str, Any] = {
            "dataview_query_params": query_params,
            "dataview_args": self.get_dataview_args(),
            "dataview_content_type_id": self.get_dataview_content_type_id(),
            "dataview_hide_filters": self.dataview_hide_filters,
            "dataview_sync_url": self.dataview_sync_url,
        }
        if token := self.get_dataview_request_token():
            ctx["dataview_request_context_id"] = issue_token(token, self.request)
        elif get_token(self.request) is not None:
            ctx["dataview_request_context_id"] = request_token_id(self.request)
        return ctx

    def get_dataview_request_token(self) -> RequestToken | None:
        """Create an independent context for a loader that supplies a layout or grant."""
        layout = self.get_dataview_token()
        permission = self.get_permission_token()
        if layout is None and permission is None:
            return None
        expiry = min(token.expiry for token in (layout, permission) if token is not None)
        return RequestToken(
            expiry=expiry,
            dataviews={layout.model: layout} if layout is not None else {},
            policies={permission.model: permission.rule} if permission is not None else {},
        )

    def get_permission_token(self) -> PermissionToken | None:
        """Return the optional permission grant for the dataview."""
        return None

    def get_dataview_token(self) -> DataviewToken | None:
        """Return the optional signed layout selection for the dataview."""
        return None
