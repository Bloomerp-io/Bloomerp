import json
from copy import copy

from django.db.models import ObjectDoesNotExist
from django.http import HttpRequest

from bloomerp.components.objects.dataviews.dataview import dataview
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.filters.parser import deserialize_filters
from bloomerp.filters.resolver import FilterFieldResolver, filters_for_tile
from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class DataViewTileRenderer(BaseTileRenderer):
    @classmethod
    def render(cls, config: DataViewTileConfig, request: HttpRequest) -> str:
        """Render a permission-aware data view from the tile configuration."""
        if config.content_type_id is None:
            return ""

        preference = None
        if config.list_view_preference_id is not None:
            try:
                preference = UserListViewPreference.objects.get(
                    id=config.list_view_preference_id
                )
            except ObjectDoesNotExist:
                pass
            if preference is not None:
                preference = preference.effective_preference

        get_params = request.GET.copy()
        if "filter" in get_params:
            resolver = None
            if get_params.get("workspace_id"):
                resolver = FilterFieldResolver.for_user("workspace", get_params["workspace_id"], request.user)
            filters = [group for value in get_params.getlist("filter") for group in deserialize_filters(value)]
            filters = filters_for_tile(filters, tile_id=get_params.get("tile_id"), resolver=resolver)
            get_params["filter"] = json.dumps([group.model_dump() for group in filters])

        for key, value in config.initial_query_params.items():
            if key in get_params or value is None:
                continue
            if isinstance(value, list):
                get_params.setlist(key, [str(item) for item in value])
            else:
                get_params[key] = str(value)

        for key in ["tile_id", "colspan", "max_cols", "workspace_id", "config"]:
            get_params.pop(key, None)

        request = copy(request)
        request.GET = get_params

        
        return dataview(
            request,
            content_type_id=config.content_type_id,
            preference=preference,
            actions=config.actions,
        ).content.decode("utf-8")
