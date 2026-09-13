from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import Locator, Response, expect

from bloomerp.lookups import builtins as lookups
from bloomerp.models import LayoutItem, LayoutRow
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.definition import RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.tests.e2e.base import BaseE2ETestCase
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, AnalyticsTileType, FieldConfig
from bloomerp.workspaces.text_tile.model import TextTileConfig
from bloomerp.workspaces.tiles import TileType


class TestWorkspaceViewE2E(BaseE2ETestCase):
    def extendedE2ESetup(self) -> None:
        pass

    def create_text_tile(
        self,
        user: AbstractBloomerpUser,
        content: str = "Hello world",
    ) -> Tile:
        return Tile.objects.create(
            name=content,
            type=TileType.TEXT_TILE.name,
            schema=TextTileConfig(markdown=content).model_dump(),
            created_by=user,
            updated_by=user,
        )

    def create_analytics_tile(
        self,
        user: AbstractBloomerpUser,
        name: str = "Analytics Tile",
        type: AnalyticsTileType = AnalyticsTileType.KPI,
        fields: dict[str, list[FieldConfig]] = None,
    ) -> Tile:
        if fields is None:
            fields = {
                "value": [
                    FieldConfig(
                        name="title",
                        opts={
                            "aggregator": "COUNT"
                        }
                    )
                ]
            }
        return Tile.objects.create(
            name=name,
            type=TileType.ANALYTICS_TILE.name,
            schema=AnalyticsTileConfig(
                query=f"SELECT * FROM {Todo._meta.db_table}",
                type=type.value.key,
                fields=fields,
                filters=[
                    AnalyticsTileFilter(
                        field="title",
                        type="text",
                        is_variable=False,
                    )
                ]
            ).model_dump(),
            created_by=user,
            updated_by=user,
        )
    
    def goto_workspace(self, workspace: Workspace) -> None:
        self.goto(f"/workspaces/{workspace.id}/")

    def create_workspace(
        self,
        user: AbstractBloomerpUser,
        name: str = "Test Workspace",
    ) -> Workspace:
        return Workspace.objects.create(
            name=name,
            user=user,
        )

    def add_tiles_to_workspace(
        self,
        workspace: Workspace,
        tiles: list[Tile],
    ) -> None:
        layout = workspace.layout_obj
        row = (
            layout.rows[0]
            if layout.rows
            else LayoutRow(columns=4, title="Row 1", items=[])
        )
        for tile in tiles:
            row.items.append(LayoutItem(id=str(tile.id), colspan=2))
        if not layout.rows:
            layout.rows.append(row)
        workspace.set_layout(layout)
        workspace.save()

    @staticmethod
    def is_layout_save_response(response: Response) -> bool:
        return (
            "/components/layout/save-layout-object/" in response.url
            and response.request.method == "POST"
        )

    def available_tile(self, tile: Tile) -> Locator:
        return self.page.locator(
            f'[data-layout-sidebar-item][data-layout-item-id="{tile.id}"]'
        )

    def workspace_tile(self, tile: Tile) -> Locator:
        return self.page.locator(
            f'[bloomerp-component="workspace-tile"]'
            f'[data-layout-item-id="{tile.id}"]'
        )

    def close_available_items_drawer(self) -> None:
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#layout-drawer-items")).to_be_hidden()

    @staticmethod
    def get_workspace_tile_ids(workspace: Workspace) -> set[str]:
        workspace.refresh_from_db()
        return {
            str(item.id)
            for row in workspace.layout_obj.rows
            for item in row.items
        }

    # ------------------------
    # TEST CASES
    # ------------------------
    # ------------------------
    # Access Control Tests
    # ------------------------
    def test_admin_can_view_any_workspace(self):
        """
        UC: An admin user can view any workspace.

        Expected Result: Admin can view any workspace
        """
        # 1. Create a workspace for the normal user.
        workspace = self.create_workspace(
            user=self.normal_user,
            name="Normal User Workspace",
        )
        self.create_text_tile(user=self.normal_user, content="Normal User Tile")
        
        # 2. Go to the workspace view as an admin user.
        self.login_as_admin()
        self.goto_workspace(workspace)

        # 3. Verify that the workspace is visible.
        expect(self.page.get_by_text("Normal User Tile")).to_be_visible()

    def test_admin_can_select_and_remove_own_tiles(self):
        """
        UC: An admin adds and removes owned tiles from a workspace.

        Expected Result: Only owned tiles are selectable and layout changes persist.
        """
        # 1. Create two admin tiles and one tile owned by another user.
        tile_1 = self.create_text_tile(user=self.admin_user, content="Admin Tile 1")
        tile_2 = self.create_text_tile(user=self.admin_user, content="Admin Tile 2")
        tile_3 = self.create_text_tile(user=self.normal_user, content="Normal User Tile")

        # 2. Create an admin workspace containing the first tile.
        workspace = self.create_workspace(
            user=self.admin_user,
            name="Admin Workspace",
        )
        self.add_tiles_to_workspace(workspace, [tile_1])

        # 3. Open the available-items drawer in edit mode.
        self.login_as_admin()
        self.goto_workspace(workspace)
        self.page.get_by_role("button", name="Edit").click()
        self.page.get_by_role("button", name="Add items").click()

        # 4. Verify ownership filtering and add the second admin tile.
        add_tile_2_button = self.available_tile(tile_2)
        expect(add_tile_2_button).to_be_visible()
        expect(self.available_tile(tile_3)).to_have_count(0)

        with self.page.expect_response(self.is_layout_save_response) as response_info:
            add_tile_2_button.click()
        self.assertTrue(response_info.value.ok)

        # 5. Close the drawer, focus the first tile, and remove it.
        self.close_available_items_drawer()
        tile_1_element = self.workspace_tile(tile_1)
        expect(tile_1_element).to_be_visible()
        tile_1_element.click()

        remove_tile_1_button = tile_1_element.locator("[data-layout-remove-item]")
        expect(remove_tile_1_button).to_be_visible()

        with self.page.expect_response(self.is_layout_save_response) as response_info:
            remove_tile_1_button.click()
        self.assertTrue(response_info.value.ok)

        # 6. Verify both layout changes were persisted.
        tile_ids = self.get_workspace_tile_ids(workspace)
        self.assertIn(str(tile_2.id), tile_ids)
        self.assertNotIn(str(tile_1.id), tile_ids)

    def test_admin_can_update_own_tile(self):
        """
        UC: An admin user can update his own tile
        
        Expected Result: Admin can update his own tile
        """
        #1. Create a tile
        tile = self.create_text_tile(user=self.admin_user, content="Admin Tile")
        
        #2. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        
        #3. Add the tile to the workspace
        self.add_tiles_to_workspace(workspace, [tile])
        
        #4. Go to the workspace view
        self.goto_workspace(workspace)
        
        self.start_codegen()
        
    def test_normal_user_can_view_shared_workspace(self):
        """
        UC: A normal user can view a workspace shared by an admin user.
        
        Expected Result: Normal user can view the shared workspace
        """
        #1. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        tile = self.create_text_tile(user=self.admin_user, content="Admin Tile")
        self.add_tiles_to_workspace(workspace, [tile])
        
        # 2. Go to the workspace view as a normal user
        workspace.shared_with_users.add(self.normal_user)
        
        # 3. Login as normal user and go to the workspace view
        self.login_as_normal_user()
        self.goto_workspace(workspace)
        
        #4. Verify that 'Admin Tile' is visible
        expect(self.workspace_tile(tile)).to_be_visible()
        
    def test_normal_user_cannot_view_unshared_workspace(self):
        """
        UC: A normal user cannot view a workspace not shared by an admin user.
        
        Expected Result: Normal user cannot view the unshared workspace
        """
        #1. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        
        # 2. Go to the workspace view as a normal user
        self.login_as_normal_user()
        self.goto_workspace(workspace)
        
        #3. Verify that there is an access denied message
        expect(self.page.get_by_text("Access Denied")).to_be_visible()
        
    def test_normal_user_can_only_view_analytics_tiles_with_own_permission_scope(self):
        """
        UC: A normal user can only view analytics tiles with their own permission scope.
        
        Expected Result: Normal user can only view analytics tiles with their own permission scope
        """
        NORMAL_USER_TODO_COUNT = 21
        ADMIN_USER_TODO_COUNT = 5
        
        NORMAL_TODO_NAME = "Normal User Todo"
        
        #1. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        
        #2. Create an analytics tile
        for _ in range(NORMAL_USER_TODO_COUNT):
            Todo.objects.create(
                title=NORMAL_TODO_NAME,
            )
        for _ in range(ADMIN_USER_TODO_COUNT):
            Todo.objects.create(
                title="Admin Todo",
            )
        
        #3. Create an analytics tile
        tile = Tile.objects.create(
            name="Analytics Tile",
            type=TileType.ANALYTICS_TILE.name,
            schema=AnalyticsTileConfig(
                query=f"SELECT * FROM {Todo._meta.db_table}",
                type=AnalyticsTileType.KPI.value.key,
                fields={
                    "value" : [
                        FieldConfig(
                            name="title",
                            opts={
                                "aggregator": "COUNT"
                            }
                        )   
                    ]
                }
            ).model_dump(),
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        self.add_tiles_to_workspace(workspace, [tile])
        
        # 4. Go to the workspace view as a normal user
        self.login_as_admin()
        self.goto_workspace(workspace)
        
        # 5. Verify that that the analytics tile shows the correct count for admin user
        expect(self.page.get_by_text(str(NORMAL_USER_TODO_COUNT+ADMIN_USER_TODO_COUNT))).to_be_visible()
        
        # 6. Add a policy to the user
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title" : [SqlExecutor.REQUIRED_PERMISSION]
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[SqlExecutor.REQUIRED_PERMISSION],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value=NORMAL_TODO_NAME
                        )
                    ]
                )
            ]
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 7. Share the workspace with the normal user
        workspace.shared_with_users.add(self.normal_user)
        
        # 8. Go to the workspace view as a normal user
        self.login_as_normal_user()
        self.goto_workspace(workspace)
        
        # 9. Verify that that the analytics tile shows the correct count for normal user
        expect(self.page.get_by_text(str(NORMAL_USER_TODO_COUNT))).to_be_visible()
        
    def test_normal_user_can_not_view_injected_tiles(self):
        """
        UC: A normal user might could inject a tile into a workspace, but that should be shielded from them.
        
        Expected Result: Normal user can not view injected tiles
        """
        # 1. Create a workspace for a normal user
        workspace = self.create_workspace(user=self.normal_user, name="Normal User Workspace")
        
        # 2. Create a tile for the admin user
        tile = self.create_text_tile(user=self.admin_user, content="Admin Tile")
        
        # 3. Add the admin tile to the normal user's workspace
        self.add_tiles_to_workspace(workspace, [tile])
        
        # 4. Go to the workspace view as a normal user
        self.login_as_normal_user()
        self.goto_workspace(workspace)
        
        # 5. Verify that the normal user cannot see the admin tile
        expect(self.workspace_tile(tile)).to_have_count(0)
        
        self.start_codegen()
    
    # ------------------------
    # Filter Tests
    # ------------------------
    def test_filters_dont_appear_if_workspace_has_no_filters(self):
        """
        UC: If a workspace has no filters, the filter button should not appear.
        
        Expected Result: The filter button does not appear if the workspace has no filters
        """
        # 1. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        
        # 2. Go to the workspace view as an admin user
        self.login_as_admin()
        self.goto_workspace(workspace)
        
        # 3. Verify that the filter button does not appear
        expect(self.page.get_by_role("button", name="Filter")).to_have_count(0)
        
    def test_filters_appear_and_work_if_workspace_has_filters(self):
        """
        UC: If a workspace has filters, the filter button should appear.
        
        Expected Result: The filter button appears if the workspace has filters
        """
        # 0. Create todos
        TYPE_1 = ("Some tile", 20)
        TYPE_2 = ("Other tile", 10)
        
        for _ in range(TYPE_1[1]):
            Todo.objects.create(
                title=TYPE_1[0],
            )
        for _ in range(TYPE_2[1]):
            Todo.objects.create(
                title=TYPE_2[0],
            )
        
        # 1. Create a workspace for the admin user
        workspace = self.create_workspace(user=self.admin_user, name="Admin Workspace")
        
        
        # 2. Create analytics tile with a filter
        tile_1 = self.create_analytics_tile(self.admin_user, name="Analytics Tile")
        tile_2 = self.create_analytics_tile(self.admin_user, name="Other Analytics Tile")
        self.add_tiles_to_workspace(workspace, [tile_1, tile_2])
        
        
        # 3. Go to the workspace view as an admin user
        self.login_as_admin()
        self.goto_workspace(workspace)
        
        # 4. Verify that the filter button appears
        expect(self.page.get_by_role("button", name="Filter")).to_be_visible()

        self.page.get_by_role("button", name="Filter").click()

        filter_container = self.page.locator(
            f"#workspace-filter-container-{workspace.id}"
        )
        field_selector = filter_container.locator(
            "#field-selector-section select"
        )

        # 5. Select the filter field and verify that the correct lookup operators appear
        with self.expect_response_for(
            reverse(
                "components_workspaces_filters_lookup_operators",
                kwargs={
                    "workspace_id": workspace.id,
                    "filter_key": "title",
                },
            ),
            method="GET",
        ) as response_info:
            field_selector.select_option("title")
        self.assertTrue(response_info.value.ok)

        operator_selector = filter_container.locator(
            "#lookup-operator-section select"
        )
        expect(operator_selector).to_be_visible()

        # 6. Select the lookup operator and verify that the correct value input appears
        with self.expect_response_for(
            reverse(
                "components_workspaces_filters_value_input",
                kwargs={
                    "workspace_id": workspace.id,
                    "filter_key": "title",
                },
            ),
            method="GET",
        ) as response_info:
            operator_selector.select_option("equals")
        self.assertTrue(response_info.value.ok)

        # 7. Fill in the value input and apply the filter
        value_input = filter_container.locator("#value-input-section input")
        expect(value_input).to_be_visible()
        value_input.fill(TYPE_1[0])

        # 8. Apply the filter and verify that the correct response is received
        workspace_content_type = ContentType.objects.get_for_model(workspace)
        with self.expect_response_for(
            reverse(
                "components_render_layout_item",
                kwargs={
                    "content_type_id": workspace_content_type.id,
                },
            ),
            method="GET",
        ) as response_info:
            self.page.get_by_role("button", name="Apply Filters").click()
        self.assertTrue(response_info.value.ok)

        # 9. Verify that the correct number of tiles are visible after applying the filter
        expect(self.workspace_tile(tile_1)).to_have_count(1)
        expect(self.workspace_tile(tile_2)).to_have_count(1)
        
        # 10. Verify that the correct number of todos are visible in the analytics tiles after applying the filter
        expect(
            self.workspace_tile(tile_1).get_by_text(str(TYPE_1[1]))
        ).to_be_visible()
        expect(
            self.workspace_tile(tile_2).get_by_text(str(TYPE_1[1]))
        ).to_be_visible()
        
        
        
        
        
        
    
        
        
        
        
