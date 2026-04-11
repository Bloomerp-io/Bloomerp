
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

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


class AnalyticsTableRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/table.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, user, data):
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
        return cls.render_to_string({"payload": payload})