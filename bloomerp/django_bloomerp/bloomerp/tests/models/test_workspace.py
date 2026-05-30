from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.workspaces.tiles import TileType


class WorkspaceModelTestCase(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def create_tile(self, name: str) -> Tile:
        return Tile.objects.create(
            name=name,
            description="",
            type=TileType.TEXT_TILE.name,
            schema={},
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

    def test_get_tiles_returns_tiles_in_layout_order(self):
        first_tile = self.create_tile("First")
        second_tile = self.create_tile("Second")
        third_tile = self.create_tile("Third")
        workspace = Workspace.objects.create(
            user=self.admin_user,
            name="Workspace",
            layout={
                "rows": [
                    {
                        "columns": 4,
                        "items": [
                            {"id": str(second_tile.pk), "colspan": 1},
                            {"id": str(first_tile.pk), "colspan": 1},
                        ],
                    },
                    {
                        "columns": 4,
                        "items": [
                            {"id": str(third_tile.pk), "colspan": 1},
                        ],
                    },
                ],
            },
        )

        self.assertEqual(
            list(workspace.get_tiles().values_list("pk", flat=True)),
            [second_tile.pk, first_tile.pk, third_tile.pk],
        )

    def test_get_tiles_ignores_stale_and_invalid_layout_ids(self):
        tile = self.create_tile("Only valid tile")
        workspace = Workspace.objects.create(
            user=self.admin_user,
            name="Workspace",
            layout={
                "rows": [
                    {
                        "columns": 4,
                        "items": [
                            {"id": "not-a-tile", "colspan": 1},
                            {"id": str(tile.pk), "colspan": 1},
                            {"id": "999999", "colspan": 1},
                        ],
                    },
                ],
            },
        )

        self.assertEqual(list(workspace.get_tiles()), [tile])
