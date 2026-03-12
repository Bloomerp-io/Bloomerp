import random
from dataclasses import dataclass

import plotly.graph_objects as go
import plotly.io as pio
from bloomerp.models.workspaces.tile import Tile
from bloomerp.router import router
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.safestring import mark_safe


@dataclass
class DummyTile:
    tile_id: int
    tile_type: str
    icon: str
    title: str
    colspan: int
    payload: dict


DUMMY_TILES = {
    9001: DummyTile(
        tile_id=9001,
        tile_type="kpi",
        icon="fa-coins",
        title="MRR",
        colspan=1,
        payload={"value": "$24.8k", "delta": "+12.4% vs last month"},
    ),
    9002: DummyTile(
        tile_id=9002,
        tile_type="table",
        icon="fa-table-list",
        title="Recent invoices",
        colspan=2,
        payload={
            "columns": ["Customer", "Status", "Amount"],
            "rows": [
                ["Acme Inc.", "Paid", "$2,450"],
                ["Northwind", "Pending", "$910"],
                ["Globex", "Overdue", "$1,120"],
            ],
        },
    ),
    9003: DummyTile(
        tile_id=9003,
        tile_type="two_dim_chart",
        icon="fa-chart-line",
        title="Pipeline trend",
        colspan=3,
        payload={
            "x": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "y": [13, 18, 15, 22, 20, 26, 24],
        },
    ),
    9004: DummyTile(
        tile_id=9004,
        tile_type="kpi",
        icon="fa-users",
        title="New customers",
        colspan=1,
        payload={"value": "184", "delta": "+8 this week"},
    ),
    9005: DummyTile(
        tile_id=9005,
        tile_type="table",
        icon="fa-list-check",
        title="Top opportunities",
        colspan=2,
        payload={
            "columns": ["Deal", "Stage", "Value"],
            "rows": [
                ["ERP rollout", "Proposal", "$44,000"],
                ["Support retainer", "Qualified", "$12,000"],
                ["Warehouse digitization", "Negotiation", "$31,500"],
            ],
        },
    ),
    9006: DummyTile(
        tile_id=9006,
        tile_type="two_dim_chart",
        icon="fa-chart-column",
        title="Weekly volume",
        colspan=4,
        payload={
            "x": ["W1", "W2", "W3", "W4"],
            "y": [4, 7, 6, 9],
        },
    ),
    9007: DummyTile(
        tile_id=9007,
        tile_type="links",
        icon="fa-link",
        title="Useful Links",
        colspan=4,
        payload={
            "links": [
                {"label": "Customer feedback", "url": "#"},
                {"label": "Sales playbook", "url": "#"},
            ]
        },
    ),
    
}


def _render_two_dim_chart_html(payload: dict) -> str:
    figure = go.Figure(
        data=[
            go.Scatter(
                x=payload.get("x", []),
                y=payload.get("y", []),
                mode="lines+markers",
                line={"color": "#3b82f6", "width": 3},
                marker={"size": 6},
            )
        ]
    )

    figure.update_layout(
        margin={"t": 8, "r": 8, "b": 28, "l": 32},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "size": 12, "color": "#334155"},
        height=176,
    )

    return pio.to_html(
        figure,
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
        default_width="100%",
        default_height="176px",
    )


@router.register(
    path="components/render_workspace_tile/",
    name="components_render_workspace_tile",
)
def render_workspace_tile(request: HttpRequest) -> HttpResponse:
    raw_tile_id = request.GET.get("tile_id")
    try:
        tile_id = int(raw_tile_id) if raw_tile_id is not None else None
    except (TypeError, ValueError):
        tile_id = None
    max_cols = int(request.GET.get("max_cols", "4")) if str(request.GET.get("max_cols", "4")).isdigit() else 4

    tile_model = Tile.objects.filter(pk=tile_id).first() if tile_id else None
    tile = None if tile_model else (DUMMY_TILES.get(tile_id) if tile_id else None)
    if tile is None and tile_model is None:
        tile = random.choice(list(DUMMY_TILES.values()))

    chart_html = ""
    if tile and tile.tile_type == "two_dim_chart":
        chart_html = _render_two_dim_chart_html(tile.payload)

    context = {
        "tile_id": tile_model.pk if tile_model else tile.tile_id,
        "tile_type": "generic" if tile_model else tile.tile_type,
        "icon": "fa-grip" if tile_model else tile.icon,
        "title": tile_model.name if tile_model else tile.title,
        "colspan": 1 if tile_model else tile.colspan,
        "max_cols": max_cols,
        "payload": {"text": tile_model.description or ""} if tile_model else tile.payload,
        "chart_html": mark_safe(chart_html),
    }
    
    return render(request, "components/workspaces/render_workspace_tile.html", context)
