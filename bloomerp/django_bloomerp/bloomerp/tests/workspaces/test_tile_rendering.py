from django.test import RequestFactory

from bloomerp.models.workspaces.tile import Tile
from bloomerp.services.workspace_services import render_tile_to_string
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.workspaces.tiles import TileType


class WorkspaceTileRenderingTests(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_text_tile_renders_template_content(self):
        """
        Use case: A workspace text tile is rendered from its saved tile configuration.
        Expected result: The tile template renders content instead of surfacing a missing template path.
        """
        # 1. Create a text tile with visible markdown content.
        tile = Tile.objects.create(
            name="KPI tile",
            description="",
            type=TileType.TEXT_TILE.name,
            schema={"markdown": "Visible workspace tile"},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        request = self.factory.get("/")
        request.user = self.admin_user

        # 2. Render the tile through the workspace rendering service.
        html = render_tile_to_string(tile, request)

        # 3. Verify the template content renders instead of the template file name.
        self.assertIn("Visible workspace tile", html)
        self.assertNotIn("cotton/workspaces/tiles/text.html", html)
