from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from bloomerp.models.workspaces.tile import Tile
from bloomerp.router import router
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.views.workspace.create_tile import (
    TILE_DESCRIPTION_SESSION_KEY,
    TILE_ICON_SESSION_KEY,
    TILE_NAME_SESSION_KEY,
    CreateTileView,
)
from django_htmx.http import HttpResponseClientRefresh

@router.register(
    path="update-tile",
    name="Update Tile",
    description="Update this tile",
    route_type="detail",
    models=Tile,
)
class UpdateTileView(CreateTileView):
    model = Tile
    
    def get_object(self) -> Tile:
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.object: Tile = self.get_object()
        self._initialize_wizard_state()

    def _initialize_wizard_state(self) -> None:
        if self.orchestrator.get_all_session_data():
            return

        schema = dict(self.object.schema or {})
        query = (schema.get("query") or "").strip()

        self.orchestrator.set_session_data("tile_type", self.object.type)
        self.orchestrator.set_session_data(TILE_NAME_SESSION_KEY, self.object.name or "")
        self.orchestrator.set_session_data(TILE_DESCRIPTION_SESSION_KEY, self.object.description or "")
        self.orchestrator.set_session_data(TILE_ICON_SESSION_KEY, self.object.icon or "")
        self.orchestrator.set_session_data("config", schema)

        print("Query", query)
        if query:
            self.orchestrator.set_session_data("query", query)

    def done(self):
        payload = self.orchestrator.get_all_session_data()

        self.object.name = payload.get(TILE_NAME_SESSION_KEY)
        self.object.description = payload.get(TILE_DESCRIPTION_SESSION_KEY)
        self.object.schema = payload.get("config")
        self.object.type = payload.get("tile_type")
        self.object.icon = payload.get(TILE_ICON_SESSION_KEY)
        self.object.updated_by = self.request.user
        self.object.save()
        
        # Add message
        self.add_message(
            text=f"Tile '{self.object.name}' updated successfully",
            type="success"
        )
        
        self.orchestrator.clear_state()
        
        return HttpResponseClientRefresh()

    def has_permission(self):
        if self.object.created_by == self.request.user:
            return True
        
        return self.request.user.is_superuser