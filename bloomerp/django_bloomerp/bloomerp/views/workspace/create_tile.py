import json

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from bloomerp.models.workspaces.tile import Tile, TileType
from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator, WizardError, WizardMixin, WizardStep
from bloomerp.widgets.code_editor_widget import CodeEditorWidget


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
        "sql_input": CodeEditorWidget(language="sql").render(
            name="query",
            value=query,
            attrs={"id": "wizard_analytics_query_input"},
        ),
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
        "visualization_type": analytics_builder.get("visualization_type", "table"),
        "builder_config_json": json.dumps(analytics_builder.get("config", {}), indent=2),
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
    tile_config = orchestrator.get_session_data("tile_config") or {}
    return {
        "config_title": tile_config.get("title", ""),
        "config_json": json.dumps(tile_config.get("config", {}), indent=2),
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


def ctx_final_config(request, view, orchestrator: BaseStateOrchestrator):
    return {
        "name": orchestrator.get_session_data("name") or "",
        "description": orchestrator.get_session_data("description") or "",
    }


def pcs_final_config(request: HttpRequest, view, orchestrator: BaseStateOrchestrator):
    orchestrator.set_session_data("name", (request.POST.get("name") or "").strip())
    orchestrator.set_session_data("description", (request.POST.get("description") or "").strip())


@router.register(
    path="create-tile",
    name="Create Tile",
    description="Create a new tile for the workspace",
)
class CreateTileView(HtmxMixin, WizardMixin, TemplateView):
    template_name = "base_wizard.html"
    session_key = "workspace_create_tile_wizard"
    htmx_skip_addendum_target = "wizard-root"

    def get_step(self, step: int) -> WizardStep | None:
        tile_type = TileType.from_key(self.orchestrator.get_session_data("tile_type"))

        if step == 0:
            return WizardStep(
                name=_("Select type"),
                template_name="workspace_views/create_tile_select_type.html",
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
                    template_name="workspace_views/create_tile_select_query.html",
                    description=_("Select or enter a query for your analytics tile"),
                    context_func=ctx_analytics_query,
                    process_func=pcs_analytics_query,
                )

            return WizardStep(
                name=_("Configure"),
                template_name="workspace_views/create_tile_type_config.html",
                description=_("Configure your selected tile"),
                context_func=ctx_type_config,
                process_func=pcs_type_config,
            )

        if step == 2:
            if tile_type == TileType.ANALYTICS_TILE:
                return WizardStep(
                    name=_("Build analytics tile"),
                    template_name="workspace_views/create_tile_analytics_builder.html",
                    description=_("Choose visualization type and basic options"),
                    context_func=ctx_analytics_builder,
                    process_func=pcs_analytics_builder,
                )

            return WizardStep(
                name=_("Final configuration"),
                template_name="workspace_views/create_tile_final_config.html",
                description=_("Set tile name and description"),
                context_func=ctx_final_config,
                process_func=pcs_final_config,
            )

        if step == 3 and tile_type == TileType.ANALYTICS_TILE:
            return WizardStep(
                name=_("Final configuration"),
                template_name="workspace_views/create_tile_final_config.html",
                description=_("Set tile name and description"),
                context_func=ctx_final_config,
                process_func=pcs_final_config,
            )

        return None

    def done(self):
        payload = self.orchestrator.get_all_session_data()
        tile_type = payload.get("tile_type")

        if not tile_type:
            return WizardError(
                message=_("No tile type was selected. Please choose a tile type first."),
                title=_("Cannot finish wizard"),
                step=0,
            )

        tile_name = (payload.get("name") or "").strip()
        if not tile_name:
            fallback_step = 3 if tile_type == TileType.ANALYTICS_TILE.name else 2
            return WizardError(
                message=_("Please provide a tile name before finishing."),
                title=_("Name required"),
                step=fallback_step,
            )

        Tile.objects.create(
            name=tile_name,
            description=payload.get("description") or "",
            schema={
                "status": "placeholder",
                "tile_type": tile_type,
                "wizard_payload": payload,
            },
            created_by=self.request.user,
            updated_by=self.request.user,
        )

        return None
