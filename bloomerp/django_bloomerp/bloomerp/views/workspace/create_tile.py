import json

from django.http import HttpRequest
from django.views.generic import TemplateView
from django.utils.translation import gettext_lazy as _

from bloomerp.workspaces.tiles import TileType
from bloomerp.models.workspaces.tile import Tile
from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator, WizardError, WizardMixin, WizardStep
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileType

CREATE_TILE_SESSION_KEY = "workspace_create_tile_wizard"


def ctx_0(request, view, orchestrator: BaseStateOrchestrator):
    selected_tile_type = orchestrator.get_session_data("tile_type")
    return {
        "selected_tile_type": selected_tile_type or "",
        "tiles": [
            {
                "key": tile_type.name,
                "name": tile_type.value.name,
                "description": tile_type.value.description,
                "icon": tile_type.value.icon,
                "selected": selected_tile_type == tile_type.name,
            }
            for tile_type in TileType
        ]
    }


def pcs_0(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    tile_type = request.POST.get("tile_type")
    if tile_type not in TileType.__members__:
        return WizardError(
            message=_("Please select a tile type to continue."),
            title=_("Selection required"),
            step=0,
        )

    orchestrator.set_session_data("tile_type", tile_type)
    orchestrator.set_session_data("query", "")
    orchestrator.set_session_data("analytics_builder", {})
    orchestrator.set_session_data("tile_config", {})


def ctx_analytics_query(request, view, orchestrator: BaseStateOrchestrator):
    query = orchestrator.get_session_data("query") or ""
    return {
        "query": query,
    }


def pcs_analytics_query(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    query = (request.POST.get("query") or "").strip()
    if not query:
        return WizardError(
            message=_("Please provide a SQL query before continuing."),
            title=_("Query required"),
            step=1,
        )

    orchestrator.set_session_data("query", query)


def ctx_analytics_builder(request, view, orchestrator: BaseStateOrchestrator):
    analytics_builder = orchestrator.get_session_data("analytics_builder") or {}
    return {
        "types" : [
            i for i in AnalyticsTileType.__members__.values()
        ]
    }


def pcs_analytics_builder(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    visualization_type = request.POST.get("visualization_type", "table")
    raw_builder_config_json = request.POST.get("builder_config_json", "")

    builder_config = {}
    if raw_builder_config_json:
        try:
            builder_config = json.loads(raw_builder_config_json)
        except json.JSONDecodeError:
            builder_config = {"raw": raw_builder_config_json}

    orchestrator.set_session_data(
        "analytics_builder",
        {
            "visualization_type": visualization_type,
            "config": builder_config,
        },
    )


def ctx_type_config(request, view, orchestrator: BaseStateOrchestrator):
    tile_type = TileType.from_key(orchestrator.get_session_data("tile_type")).value

    if tile_type.form_cls:
        form = tile_type.form_cls()
    
    return {
        "form" : form if tile_type.form_cls else None,
    }


def pcs_type_config(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    config_title = (request.POST.get("config_title") or "").strip()
    raw_config_json = request.POST.get("config_json", "")

    config_json = {}
    if raw_config_json:
        try:
            config_json = json.loads(raw_config_json)
        except json.JSONDecodeError:
            config_json = {"raw": raw_config_json}

    orchestrator.set_session_data(
        "tile_config",
        {
            "title": config_title,
            "config": config_json,
        },
    )


BUILDER_STEP = WizardStep(
    name=_("Build tile"),
    description=_("Configure the details of your tile and preview what it looks like."),
    template_name="workspace_views/create_tile_wizard/create_tile_analytics_builder.html",
    context_func=ctx_analytics_builder,
    process_func=pcs_analytics_builder,
)

@router.register(
    path="create-tile",
    name="Create Tile",
    description="Create a new tile for the workspace",
)
class CreateTileView(WizardMixin, HtmxMixin, TemplateView):
    template_name = "base_wizard.html"
    session_key = CREATE_TILE_SESSION_KEY
    htmx_include_addendum = False

    def get_step(self, step: int) -> WizardStep | None:
        tile_type = TileType.from_key(self.orchestrator.get_session_data("tile_type"))



        if step == 0:
            return WizardStep(
                name=_("Select type"),
                template_name="workspace_views/create_tile_wizard/create_tile_select_type.html",
                description=_("Select the type of tile you want to create"),
                context_func=ctx_0,
                process_func=pcs_0,
            )

        if tile_type is None:
            return None

        if step == 1:
            if tile_type == TileType.ANALYTICS_TILE:
                return WizardStep(
                    name=_("Select query"),
                    template_name="workspace_views/create_tile_wizard/create_tile_select_query.html",
                    description=_("Select or enter a query for your analytics tile"),
                    context_func=ctx_analytics_query,
                    process_func=pcs_analytics_query,
                )

            return BUILDER_STEP

        if step == 2:
            if tile_type == TileType.ANALYTICS_TILE:
                return BUILDER_STEP
        
        return None

    def done(self):
        payload = self.orchestrator.get_all_session_data()
        print("Final payload:", payload)
        return None
