from bloomerp.router import router
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator
from bloomerp.views.workspace.create_tile import CREATE_TILE_SESSION_KEY
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileType
from bloomerp.workspaces.tiles import TileType
from django.views.generic import TemplateView

@router.register(
    path="components/preview_workspace_tile/",
    name="preview_workspace_tile",
)
class PreviewWorkspaceTile(TemplateView):
    template_name = "components/workspaces/preview_workspace_tile.html"

    def get_orchestrator(self) -> BaseStateOrchestrator:
        """Returns the state orchestrator for the tile creation wizard."""
        return BaseStateOrchestrator(
            self.request,
            CREATE_TILE_SESSION_KEY
        )

    def get_tile_type(self) -> TileType:
        """Returns the tile type definition"""
        orchestrator = self.get_orchestrator()
        tile_type_key = orchestrator.get_session_data("tile_type")
        if not tile_type_key:
            return None

        return TileType.from_key(tile_type_key)

    def render_tile_preview(self) -> str:
        """Renders the tile preview based on the current tile configuration in the session."""
        return "<p class='text-primary text-2xl'>Hello world<p>"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["tile_builder_template_name"] = self.get_tile_builder_template()
        ctx["tile_preview_html"] = self.render_tile_preview()
        ctx.update(
            self.get_extra_context()
        )
        return ctx
    
    def get_tile_builder_template(self):
        """Returns the appropriate tile builder template based on the tile type."""
        match self.get_tile_type():
            case TileType.ANALYTICS_TILE:
                return "components/workspaces/tile_builders/analytics_tile.html"
            case _:
                return "components/workspaces/tile_builders/default_tile_builder.html"

    def get_extra_context(self) -> dict:
        """Returns any extra context needed for rendering the tile preview."""
        match self.get_tile_type():
            case TileType.ANALYTICS_TILE:
                
                return {
                    "types" : [
                        i for i in AnalyticsTileType.__members__.values()
                    ]
                }
            case _:
                return {}
            