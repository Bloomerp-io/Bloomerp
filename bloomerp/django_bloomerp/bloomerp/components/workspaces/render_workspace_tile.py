import random
from dataclasses import dataclass

import plotly.graph_objects as go
import plotly.io as pio
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
    1: DummyTile(
        tile_id=1,
        tile_type="kpi",
        icon="fa-coins",
        title="MRR",
        colspan=1,
        payload={"value": "$24.8k", "delta": "+12.4% vs last month"},
    ),
    2: DummyTile(
        tile_id=2,
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
    3: DummyTile(
        tile_id=3,
        tile_type="two_dim_chart",
        icon="fa-chart-line",
        title="Pipeline trend",
        colspan=3,
        payload={
            "x": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "y": [13, 18, 15, 22, 20, 26, 24],
        },
    ),
    4: DummyTile(
        tile_id=4,
        tile_type="kpi",
        icon="fa-users",
        title="New customers",
        colspan=1,
        payload={"value": "184", "delta": "+8 this week"},
    ),
    5: DummyTile(
        tile_id=5,
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
    6: DummyTile(
        tile_id=6,
        tile_type="two_dim_chart",
        icon="fa-chart-column",
        title="Weekly volume",
        colspan=4,
        payload={
            "x": ["W1", "W2", "W3", "W4"],
            "y": [4, 7, 6, 9],
        },
    ),
    7: DummyTile(
        tile_id=7,
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


@router.route(
    path="components/render_workspace_tile/",
    name="components_render_workspace_tile",
)
def render_workspace_tile(request: HttpRequest) -> HttpResponse:
    raw_tile_id = request.GET.get("tile_id")
    tile_id = int(raw_tile_id) if raw_tile_id and raw_tile_id.isdigit() else random.choice(list(DUMMY_TILES.keys()))

    tile = DUMMY_TILES.get(tile_id) or random.choice(list(DUMMY_TILES.values()))

    chart_html = ""
    if tile.tile_type == "two_dim_chart":
        chart_html = _render_two_dim_chart_html(tile.payload)

    context = {
        "tile_id": tile.tile_id,
        "tile_type": tile.tile_type,
        "icon": tile.icon,
        "title": tile.title,
        "colspan": tile.colspan,
        "max_cols": 4,
        "payload": tile.payload,
        "chart_html": mark_safe(chart_html),
    }

    return render(request, "components/workspaces/render_workspace_tile.html", context)
