from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
    from bloomerp.workspaces.analytics_tile.model import FieldConfig


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _field_label(field: FieldConfig | None) -> str:
    if field is None:
        return ""

    label = (field.opts or {}).get("label")
    return label or field.name


def _field_color(field: FieldConfig | None) -> str | None:
    if field is None:
        return None

    color = (field.opts or {}).get("color")
    return color or None


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


def _apply_text_x_axis_order(data: pd.DataFrame, x_axis: str, order: str | None) -> pd.DataFrame:
    raw_values = [value.strip() for value in (order or "").split(",") if value.strip()]
    if not raw_values:
        return data

    next_data = data.copy()
    next_data["__original_order"] = range(len(next_data))
    order_index = {value: index for index, value in enumerate(raw_values)}
    next_data["__sort_order"] = next_data[x_axis].astype(str).map(lambda value: order_index.get(value, len(order_index)))
    next_data = next_data.sort_values(["__sort_order", "__original_order"], kind="stable")
    return next_data.drop(columns=["__original_order", "__sort_order"])


def _render_plotly_chart_html(figure: go.Figure) -> str:
    return pio.to_html(
        figure,
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
        default_width="100%",
        default_height="176px",
    )

class AnalyticsTwoDimChartRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/two_dim_chart.html"

    @classmethod
    def render(cls, config: AnalyticsTileConfig, user, data):
        x_axis_field = next(iter(config.fields.get("x_axis") or []), None)
        y_axis_fields = list(config.fields.get("y_axis") or [])

        if x_axis_field is None or not y_axis_fields:
            return "<p>Please add chart fields.</p>"

        x_axis = x_axis_field.name
        if x_axis not in data.columns:
            return "<p>Please add chart fields.</p>"

        opts = config.opts or {}
        chart_type = opts.get("chart_type") or "line"
        if chart_type not in {"line", "scatter", "bar"}:
            chart_type = "line"

        if pd.api.types.is_object_dtype(data[x_axis]) or pd.api.types.is_string_dtype(data[x_axis]):
            data = _apply_text_x_axis_order(data, x_axis, opts.get("x_axis_order"))

        stacked = _is_truthy(opts.get("stacked")) and len(y_axis_fields) > 1
        show_legend_opt = opts.get("show_legend")
        show_legend = len(y_axis_fields) > 1 if show_legend_opt in (None, "") else _is_truthy(show_legend_opt)
        fig = go.Figure()
        x_values = data[x_axis].tolist()

        for y_axis_field in y_axis_fields:
            if y_axis_field.name not in data.columns:
                continue

            trace_name = _field_label(y_axis_field)
            y_values = data[y_axis_field.name].tolist()
            color = _field_color(y_axis_field)

            if chart_type == "bar":
                fig.add_trace(
                    go.Bar(
                        x=x_values,
                        y=y_values,
                        name=trace_name,
                        marker={"color": color} if color else None,
                    )
                )
                continue

            trace_kwargs = {
                "x": x_values,
                "y": y_values,
                "name": trace_name,
            }
            if color:
                trace_kwargs["line"] = {"color": color}
                trace_kwargs["marker"] = {"color": color}
            if chart_type == "scatter":
                trace_kwargs["mode"] = "markers"
            else:
                trace_kwargs["mode"] = "lines+markers"
                if stacked:
                    trace_kwargs["stackgroup"] = "stack"

            fig.add_trace(go.Scatter(**trace_kwargs))

        if not fig.data:
            return "<p>Please add chart fields.</p>"

        fig.update_layout(
            margin={"t": 8, "r": 8, "b": 28, "l": 32},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"family": "Inter, system-ui, sans-serif", "size": 12, "color": "#334155"},
            height=176,
            xaxis_title=opts.get("x_axis_label") or None,
            yaxis_title=opts.get("y_axis_label") or None,
            yaxis={"rangemode": "tozero"} if chart_type == "line" else None,
            barmode="stack" if stacked and chart_type == "bar" else "group",
            showlegend=show_legend,
            legend=_legend_layout(opts.get("legend_position") or "right"),
        )

        return cls.render_to_string(
            {
                "chart_html": _render_plotly_chart_html(fig),
            }
        )




        
        