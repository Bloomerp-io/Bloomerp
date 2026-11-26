import json
from copy import copy
from datetime import timedelta

from django.http import HttpRequest
from django.utils import timezone

from bloomerp.components.objects.dataviews.dataview import dataview
from bloomerp.filters.parser import deserialize_filters
from bloomerp.filters.resolver import FilterFieldResolver, filters_for_tile
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tokens import (
    REQUEST_TOKEN_QUERY_KEYS,
    DataviewToken,
    RequestToken,
    issue_token,
    request_query_params,
)
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class DataViewTileRenderer(BaseTileRenderer):
    @classmethod
    def render(cls, config: DataViewTileConfig, request: HttpRequest) -> str:
        """Render a permission-aware data view from the tile configuration."""
        if config.content_type_id is None:
            return ""

        model, content_type = get_model_and_content_type_or_404(config.content_type_id)
        preference = None
        if config.list_view_preference_id is not None:
            preference = UserListViewPreference.objects.filter(
                pk=config.list_view_preference_id, content_type=content_type,
            ).first()
            if preference is not None:
                preference = preference.effective_preference
        if preference is None:
            preference = PreferenceManager(request.user).get_or_create_selected(
                UserListViewPreference, {"content_type_id": content_type.pk},
            )

        get_params = request_query_params(request)
        if "filter" in get_params:
            resolver = None
            if get_params.get("workspace_id"):
                resolver = FilterFieldResolver.for_user("workspace", get_params["workspace_id"], request.user)
            filters = [group for value in get_params.getlist("filter") for group in deserialize_filters(value)]
            filters = filters_for_tile(filters, tile_id=get_params.get("tile_id"), resolver=resolver)
            get_params["filter"] = json.dumps([group.model_dump() for group in filters])

        for key, value in config.initial_query_params.items():
            if key in REQUEST_TOKEN_QUERY_KEYS or key in get_params or value is None:
                continue
            if isinstance(value, list):
                get_params.setlist(key, [str(item) for item in value])
            else:
                get_params[key] = str(value)

        for key in ["tile_id", "colspan", "max_cols", "workspace_id", "config"]:
            get_params.pop(key, None)

        expiry = timezone.now() + timedelta(days=1)
        layout = DataviewToken(
            preference_id=preference.pk,
            dataview_actions=config.actions,
        )
        request = copy(request)
        request.GET = get_params
        issue_token(RequestToken(
            expiry=expiry,
            dataviews={model: layout},
        ), request, activate=True)

        return dataview(request, content_type_id=content_type.pk).content.decode("utf-8")
