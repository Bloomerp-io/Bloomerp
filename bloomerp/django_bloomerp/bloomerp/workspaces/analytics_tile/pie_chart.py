from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

from bloomerp.workspaces.analytics_tile.utils import Formatter
from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
    from bloomerp.workspaces.analytics_tile.model import FieldConfig


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_bool_option(value, *, default: bool) -> bool:
    if value is None:
        return default
    return _is_truthy(value)


def _field_label(field: FieldConfig | None) -> str:
    if field is None:
        return ""

    label = (field.opts or {}).get("label")
    return label or field.name


def _legend_layout(position: str | None) -> dict:
    match position:
        case "top":
            return {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0}
        case "bottom":
            return {"orientation": "h", "yanchor": "top", "y": -0.2, "xanchor": "left", "x": 0}
        case "left":
            return {"orientation": "v", "yanchor": "top", "y": 1, "xanchor": "right", "x": -0.05}
        case _:
            return {"orientation": "v", "yanchor": "top", "y": 1, "xanchor": "left", "x": 1.02}


def _render_plotly_chart_html(figure: go.Figure) -> str:
    return pio.to_html(
        figure,
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
        default_width="100%",
        default_height="176px",
    )


def _normalize_value(value):
    if pd.isna(value):
        return None
    return value


def _format_value(value, field: FieldConfig) -> str:
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


class AnalyticsPieChartRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/pie_chart.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, user, data):
        label_field = next(iter(config.fields.get("labels") or []), None)
        value_field = next(iter(config.fields.get("values") or []), None)

        if label_field is None or value_field is None:
            return "<p>Please add pie chart fields.</p>"

        if label_field.name not in data.columns or value_field.name not in data.columns:
            return "<p>Please add pie chart fields.</p>"

        grouped_data = (
            data.groupby(label_field.name, dropna=False)[value_field.name]
            .sum()
            .reset_index()
        )

        if grouped_data.empty:
            return "<p>Please add pie chart fields.</p>"

        labels = ["" if value is None else str(value) for value in grouped_data[label_field.name].tolist()]
        values = grouped_data[value_field.name].tolist()
        formatted_values = [_format_value(value, value_field) for value in values]
        opts = config.opts or {}
        show_legend = _resolve_bool_option(opts.get("show_legend"), default=True)

        fig = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    customdata=formatted_values,
                    textinfo="label+percent",
                    hovertemplate=f"%{{label}}<br>{_field_label(value_field)}: %{{customdata}}<extra></extra>",
                    showlegend=show_legend,
                )
            ]
        )

        fig.update_layout(
            margin={"t": 8, "r": 8, "b": 28, "l": 8},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"family": "Inter, system-ui, sans-serif", "size": 12, "color": "#334155"},
            height=176,
            showlegend=show_legend,
            legend=_legend_layout(opts.get("legend_position") or "right"),
        )

        return cls.render_to_string(
            {
                "chart_html": _render_plotly_chart_html(fig),
            }
        )