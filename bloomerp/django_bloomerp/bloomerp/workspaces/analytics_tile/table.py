
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.http import HttpRequest
from django.urls import reverse
import pandas as pd


from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.utils import Formatter
from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
    from bloomerp.workspaces.analytics_tile.model import FieldConfig


def _normalize_value(value):
    if pd.isna(value):
        return None
    return value


def _format_value(value, field: FieldConfig):
    field_opts = field.opts or {}
    value = _normalize_value(value)

    formatter_name = field_opts.get("formatter")
    if formatter_name and formatter_name != "NONE":
        value = Formatter[formatter_name].value.func(value)

    if value is None:
        value = ""

    prefix = field_opts.get("prefix") or ""
    suffix = field_opts.get("suffix") or ""
    return f"{prefix}{value}{suffix}"


def _get_column_label(field: FieldConfig) -> str:
    label = (field.opts or {}).get("label")
    return label or field.name


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_pagination_range(current_page: int, total_pages: int, window: int = 2) -> list[int | None]:
    if total_pages <= 1:
        return [1]

    pages: list[int | None] = [1]

    start = max(2, current_page - window)
    end = min(total_pages - 1, current_page + window)

    if start > 2:
        pages.append(None)

    pages.extend(range(start, end + 1))

    if end < total_pages - 1:
        pages.append(None)

    pages.append(total_pages)
    return pages

# TODO: Not the best piece of code bcs of coupling with endpoint but okay
def get_renderer_url() -> str:
    from bloomerp.models.workspaces.workspace import Workspace
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Workspace)
    return reverse(
        "components_render_layout_item",
        kwargs={
            "content_type_id" : ct.id
        }
    )
    

class AnalyticsTableRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/table.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, request:HttpRequest):
        from bloomerp.workspaces.analytics_tile.model import get_filtered_query

        # Get the query parameters
        page = _to_int(request.GET.get("page", 1), 1)
        tile_id = request.GET.get("tile_id")
        colspan = max(1, _to_int(request.GET.get("colspan", 1), 1))
        max_cols = max(1, _to_int(request.GET.get("max_cols", 4), 4))
        
        # Get the query
        query = get_filtered_query(config, request.GET)

        # Get the data
        sql_response = SqlExecutor(request.user).execute_query(
            query=query,
            page=page,
            page_size=int(config.opts.get("page_size", 10))
            )
        data = sql_response.to_dataframe()

        selected_fields = config.fields.get("columns") or []
        payload = {
            "columns": [_get_column_label(field) for field in selected_fields],
            "rows": [],
        }

        if not selected_fields:
            return cls.render_to_string({"payload": payload})

        rows = []
        for _, row in data.iterrows():
            rendered_row = []
            for field in selected_fields:
                value = row[field.name] if field.name in data.columns else None
                rendered_row.append(_format_value(value, field))
            rows.append(rendered_row)

        payload["rows"] = rows
        pagination_params = request.GET.copy()
        pagination_params.pop("page", None)
        pagination_params["colspan"] = str(colspan)
        pagination_params["max_cols"] = str(max_cols)
        if tile_id:
            pagination_params["tile_id"] = tile_id
        pagination_querystring = urlencode(pagination_params, doseq=True)

        return cls.render_to_string(
            {
                "payload": payload,
                "tile_id" : tile_id,
                "url": get_renderer_url(),
                "current_page": sql_response.page,
                "total_pages": sql_response.total_pages,
                "has_previous": sql_response.page > 1,
                "has_next": sql_response.page < sql_response.total_pages,
                "previous_page_number": sql_response.page - 1,
                "next_page_number": sql_response.page + 1,
                "pagination_pages": _build_pagination_range(sql_response.page, sql_response.total_pages),
                "show_global_pagination": sql_response.total_pages > 1,
                "result_start": sql_response.page_start,
                "result_end": sql_response.page_end,
                "result_count": sql_response.row_count,
                "pagination_querystring": pagination_querystring,
                }
            )
    
    
