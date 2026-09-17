from django.test import RequestFactory, SimpleTestCase

from bloomerp.dataviews.definition import DataviewTypeDefinition
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.dataviews.table.renderer import TableDataviewRenderer
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.services.workspace_services import (
    render_tile_to_string,
    resolve_tile_type_from_config,
)
from bloomerp.views.workspaces.create_tile import ctx_0, pcs_0
from bloomerp.workspaces.base import BaseTileConfig, BaseTileRenderer, TileTypeDefinition
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY


class ExternalTileConfig(BaseTileConfig):
    content: str = "Extension content"

    @classmethod
    def get_default(cls, *args, **kwargs):
        return cls()

    @classmethod
    def get_operation(cls, operation):
        raise KeyError(operation)


class ExternalTileRenderer(BaseTileRenderer):
    @classmethod
    def render(cls, config, request, *args, **kwargs):
        return f"<div>{config.content}</div>"


class SessionDataStub:
    def __init__(self):
        self.data = {}

    def get_session_data(self, key):
        return self.data.get(key)

    def set_session_data(self, key, value):
        self.data[key] = value


class ExtensibleViewRegistryTests(SimpleTestCase):
    def test_registered_tile_is_available_to_models_creation_and_rendering(self):
        """
        Use case:
        An extension registers a complete custom tile type after model import.
        Expected result:
        The tile can be selected, validated, persisted, resolved, and rendered.
        """
        key = "EXTERNAL_TILE"
        definition = TileTypeDefinition(
            name="External Tile",
            description="A tile supplied by an extension.",
            model=ExternalTileConfig,
            render_cls=ExternalTileRenderer,
        )
        orchestrator = SessionDataStub()

        try:
            # 1. Register the external definition after the Tile model is imported.
            TILE_TYPE_REGISTRY.register(key, definition)

            # 2. Confirm Django and the creation wizard expose the live registry item.
            self.assertIn((key, "External Tile"), Tile._meta.get_field("type").flatchoices)
            self.assertIn(key, {tile["key"] for tile in ctx_0(None, None, orchestrator)["tiles"]})

            # 3. Submit the external key through the wizard validation path.
            request = RequestFactory().post("/create-tile", {"tile_type": key})
            self.assertIsNone(pcs_0(request, None, orchestrator))
            self.assertEqual(orchestrator.get_session_data("tile_type"), key)

            # 4. Resolve and render a Tile using only the registered definition.
            config = ExternalTileConfig(content="Rendered by extension")
            self.assertEqual(resolve_tile_type_from_config(config), key)
            tile = Tile(
                name="External",
                type=key,
                schema=config.model_dump(),
                auto_generated=False,
            )
            rendered = render_tile_to_string(tile, RequestFactory().get("/"))
            self.assertEqual(rendered, "<div>Rendered by extension</div>")
        finally:
            TILE_TYPE_REGISTRY.unregister(key)

    def test_registered_dataview_is_available_in_model_choices(self):
        """
        Use case:
        An extension registers a dataview after UserListViewPreference is imported.
        Expected result:
        Django evaluates the current registry when it resolves field choices.
        """
        key = "external_view"
        definition = DataviewTypeDefinition(
            key=key,
            label="External view",
            description="A dataview supplied by an extension.",
            icon="fa-puzzle-piece",
            renderer_cls=TableDataviewRenderer,
            config_cls=TableDataView,
        )

        try:
            # 1. Register the external definition after the model is imported.
            DATAVIEW_REGISTRY.register(key, definition)

            # 2. Ask Django for choices and verify it invokes the callable now.
            choices = UserListViewPreference._meta.get_field("view_type").flatchoices
            self.assertIn((key, "External view"), choices)
        finally:
            # 3. Restore the process-wide registry for following tests.
            DATAVIEW_REGISTRY.unregister(key)
